import pytest
from odl import utils
from odl_kernel.types import JobStatus, LifecycleStatus

SCENARIO_ID = "sc99_job_failure"
SCENARIO_YAML = """
serial:
  stack_path: root
  children:
    # 1. タイムアウト等で失敗するWorker
    - worker:
        stack_path: root/bad_worker
        inputs: []
        output: Out
"""

class TestJobFailure:
    def test_run(self, simulator_cls):
        # 1. Setup
        ir_root = utils.load_ir_from_spec(SCENARIO_YAML)
        sim = simulator_cls(ir_root=ir_root, job_id=SCENARIO_ID)
        
        # Bootstrap
        sim.tick()
        
        # 2. Workerを強制的に失敗させる (Timeout or Error)
        # Note: harness.py に fail_node 相当の機能がない場合は、
        #       sim.nodes[target_id].lifecycle_status = FAILED を直接行うか、
        #       TransitionRulesのTimeoutロジックを利用して時間を進める
        
        # ここでは擬似的に Timeout を発生させる
        target_suffix = "root/bad_worker"
        node = sim._resolve_target_node(None, target_suffix)
        node.timeout_at = 0 # 過去の時間に設定
        
        # 3. Analyze (Timeout検知 -> Worker Failed -> Serial Failed -> Job Failed)
        result = sim.tick(delta_seconds=1.0)
        sim.dump_analysis_result(result, "02_failure_propagation")

        # 4. Verification
        # RootノードがFAILEDになっていること
        sim.assert_node_status("root", LifecycleStatus.FAILED)
        
        # 【重要】JobUpdateが発行され、ステータスがFAILEDになっていること
        assert result.job_update is not None
        assert result.job_update.status == JobStatus.FAILED
        assert sim.job.status == JobStatus.FAILED