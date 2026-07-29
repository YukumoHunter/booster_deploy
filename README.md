# Booster Squat Deploy

This repository deploys the toggle-controlled Booster K1 squat policy in
MuJoCo or on a real robot. The ONNX model owns the reversible squat state
machine; deployment only persists its opaque state and supplies the operator's
enabled/disabled command.

## Install

[Pixi](https://pixi.sh) manages the Python environment on Linux x86-64 and
ARM64:

```bash
pixi install --locked
```

MuJoCo also needs the robot data checkout. The upstream Python wheel does not
contain the XML and mesh assets, so point deployment at the checkout itself:

```bash
git clone https://github.com/BoosterRobotics/booster_assets ../booster_assets
export BOOSTER_ASSETS_DIR="$(realpath ../booster_assets)"
```

For real-robot control, Booster firmware 1.4 or newer and the firmware-provided
ROS 2 `booster_interface` package are still required. The `deploy` Pixi task
automatically sources both the ROS 2 installation and Booster interface overlay:

```bash
source /opt/ros/humble/setup.bash
source /opt/booster/BoosterRos2Interface/install/setup.bash
```

The Pixi environment uses Python 3.10 to remain ABI-compatible with the
Ubuntu 22.04 ROS 2 Humble installation. `rclpy` is loaded from
`/opt/ros/humble`, while `booster_interface` is loaded from the Booster overlay;
they are intentionally not installed by Pixi.

The high-level mode client is Booster Robotics' original
[`booster-robotics-sdk-python`](https://pypi.org/project/booster-robotics-sdk-python/),
installed by Pixi from PyPI. The IntelligentRoboticsLab `booster-sdk` package is
not used.

## Run

The sole task is `squat`, so it is selected when `--task` is omitted:

```bash
pixi run list-tasks
pixi run deploy-mujoco
pixi run deploy
```

Run `pixi run deploy` on the robot, where both setup scripts are installed.
MuJoCo deployment does not source ROS and can be run on a development machine.

`pixi run deploy --task squat` remains available for explicit selection.
Use `--webots` with `deploy` when the ROS topics are provided by Webots.

On the real robot, press joystick A (keyboard `x`) to enter custom mode, then
joystick B (keyboard `r`) to start the policy. After startup, joystick B or
keyboard `s` toggles squat on and off. In MuJoCo, joystick B or keyboard `s`
toggles immediately.

MuJoCo initializes the robot directly from the model's embedded frame-zero
root pose, orientation, and joint positions.

## Stateful ONNX contract

The model inputs are `obs`, `squat_enabled`, and `squat_state_in`. Every call
returns actions, `squat_state_out`, and the next reference arrays. Deployment
feeds the returned state and references into the next control step without
interpreting the state machine. Startup and policy reset restore disabled
standing state `[0, 0, 1]` and the embedded frame-zero reference.

The policy observation intentionally omits trunk translation and base linear
velocity, so the same 122-value observation is constructed from signals
available in both MuJoCo and on the real robot.

## Development

```bash
pixi run test
pixi run lint
```

The tracked policy artifact is `tasks/squat/models/squat.onnx`. Its metadata is
validated at startup and is the source of truth for observation layout, joint
order, default positions, gains, and action scaling.
