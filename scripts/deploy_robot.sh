#!/usr/bin/env bash

set -euo pipefail

source /opt/ros/humble/setup.bash
source /opt/booster/BoosterRos2Interface/install/setup.bash

# ROS setup may put the robot's older system libstdc++ ahead of Pixi's native
# libraries. ONNX Runtime requires the newer C++ ABI supplied by this Pixi env.
if [[ -z "${CONDA_PREFIX:-}" ]]; then
    echo "Error: deploy_robot.sh must be run inside the Pixi environment." >&2
    exit 1
fi
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

exec python scripts/deploy.py "$@"
