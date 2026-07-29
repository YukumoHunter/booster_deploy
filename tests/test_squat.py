from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch

from booster_deploy.controllers.base_controller import BoosterRobot
from booster_deploy.robots.booster import K1_CFG
from booster_deploy.utils.remote_control_service import RemoteControlService
from tasks.squat.squat import OUTPUT_NAMES, SquatPolicy, SquatPolicyCfg
from tasks.squat.squat import HEAD_ACTION_SCALE_MULTIPLIER


MODEL = Path(__file__).parents[1] / "tasks/squat/models/squat.onnx"


class FakeController:
    def __init__(self):
        self.robot = BoosterRobot(K1_CFG)
        self.robot.data.root_quat_w = torch.tensor([1.0, 0.0, 0.0, 0.0])
        self.squat_enabled = False
        self.stopped = False

    def stop(self):
        self.stopped = True


class SquatPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller = FakeController()
        cls.policy = SquatPolicy(
            SquatPolicyCfg(checkpoint_path="models/squat.onnx"), cls.controller
        )

    def setUp(self):
        self.controller.squat_enabled = False
        self.policy.reset()

    def test_model_contract(self):
        session = ort.InferenceSession(
            str(MODEL), providers=["CPUExecutionProvider"]
        )
        self.assertEqual([item.name for item in session.get_inputs()], [
            "obs", "squat_enabled", "squat_state_in"
        ])
        self.assertEqual(
            [item.name for item in session.get_outputs()], list(OUTPUT_NAMES)
        )

    def test_observation_omits_translational_state(self):
        observation = self.policy.compute_observation()
        self.assertEqual(observation.shape, (1, 122))

    def test_initial_motion_anchor_orientation_is_identity(self):
        self.controller.robot.data.root_quat_w = torch.from_numpy(
            self.policy.ref_body_quat_w[self.policy.anchor_index].copy()
        )
        self.policy.reset()

        observation = self.policy.compute_observation()[0]
        np.testing.assert_allclose(
            observation[44:50],
            np.eye(3, dtype=np.float32)[:, :2].reshape(-1),
            atol=1e-6,
        )

    def test_initial_qpos_is_embedded_standing_reference(self):
        qpos = self.policy.get_initial_qpos()
        self.assertEqual(qpos.shape, (29,))
        np.testing.assert_allclose(
            qpos[:3], self.policy.ref_body_pos_w[self.policy.anchor_index]
        )
        np.testing.assert_allclose(
            qpos[3:7], self.policy.ref_body_quat_w[self.policy.anchor_index]
        )
        np.testing.assert_allclose(
            qpos[7:][self.policy.policy_to_robot], self.policy.ref_joint_pos
        )

    def test_head_action_scale_is_reduced(self):
        exported_scale = np.asarray(
            [
                float(value)
                for value in self.policy.metadata["action_scale"].split(",")
            ],
            dtype=np.float32,
        )
        head_indices = [
            self.policy.policy_joint_names.index(name)
            for name in ("Head_Yaw", "Head_Pitch")
        ]
        np.testing.assert_allclose(
            self.policy.action_scale[head_indices],
            exported_scale[head_indices] * HEAD_ACTION_SCALE_MULTIPLIER,
        )
        body_indices = np.setdiff1d(
            np.arange(len(exported_scale)), head_indices
        )
        np.testing.assert_allclose(
            self.policy.action_scale[body_indices], exported_scale[body_indices]
        )

    def test_toggle_advances_and_state_is_persisted(self):
        np.testing.assert_array_equal(
            self.policy.squat_state, np.asarray([[0, 0, 1]], dtype=np.int64)
        )
        self.controller.squat_enabled = True
        targets = self.policy.inference()
        np.testing.assert_array_equal(self.policy.squat_state, [[1, 1, 1]])
        self.assertEqual(tuple(targets.shape), (22,))

        self.controller.squat_enabled = False
        self.policy.inference()
        np.testing.assert_array_equal(self.policy.squat_state, [[0, 0, 1]])

    def test_loop_exit_and_ascent_reversal(self):
        self.controller.squat_enabled = True
        for _ in range(75):
            self.policy.inference()
        np.testing.assert_array_equal(self.policy.squat_state, [[75, 2, 1]])

        self.controller.squat_enabled = False
        self.policy.inference()
        np.testing.assert_array_equal(self.policy.squat_state, [[123, 3, 1]])

        self.controller.squat_enabled = True
        self.policy.inference()
        np.testing.assert_array_equal(self.policy.squat_state, [[122, 2, -1]])


class RemoteControlTest(unittest.TestCase):
    def test_keyboard_s_latches_toggle(self):
        service = RemoteControlService.__new__(RemoteControlService)
        service._lock = __import__("threading").Lock()
        service._toggle_armed = True
        service._squat_enabled = False
        service._custom_mode_requested = False
        service._policy_start_requested = False
        service._handle_keyboard_press("s")
        self.assertTrue(service.get_squat_enabled())
        service._handle_keyboard_press("s")
        self.assertFalse(service.get_squat_enabled())


if __name__ == "__main__":
    unittest.main()
