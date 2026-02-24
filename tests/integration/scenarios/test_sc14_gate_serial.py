import pytest
from odl import utils
from odl_kernel.types import LifecycleStatus, BusinessResult, CommandType

# =========================================================================
# SECTION 1: SCENARIO DEFINITION
# =========================================================================

SCENARIO_ID = "sc14_simple_approval_gate"

# cocrea.5120.yml: Case 2_1_1 expansion_ir (Physical IR)
SCENARIO_YAML = """
serial:
  stack_path: root/serial_0
  children:
    - loop:
        stack_path: root/serial_0/loop_0
        count: 10
        break_on: success
        contents:
          serial:
            stack_path: root/serial_0/loop_0/v{$LOOP}/serial_0
            children:
              - worker:
                  stack_path: root/serial_0/loop_0/v{$LOOP}/serial_0/worker_0
                  agent: ProjectArchitect
                  mode: generate
                  inputs: 
                    - 全社規定:Rules01@stable
                    - 市場レポート:Mkt05@latest
                    - プロジェクト定義書#default/v{$LOOP-1}
                    - プロジェクト定義書__Review_ProjectManager#default/v{$LOOP-1}
                  output: プロジェクト定義書#default/v{$LOOP}
              - approver:
                  stack_path: root/serial_0/loop_0/v{$LOOP}/serial_0/approver_1
                  agent: ProjectManager
                  inputs: 
                    - プロジェクト定義書#default/v{$LOOP}                        
                    - プロジェクト定義書#default/v{$LOOP-1}
                    - プロジェクト定義書__Review_ProjectManager#default/v{$LOOP-1}
                    - 全社規定:Rules01@stable
                    - 市場レポート:Mkt05@latest
                  output: プロジェクト定義書__Review_ProjectManager#default/v{$LOOP}
    - scope_resolve:
        stack_path: root/serial_0/scope_resolve_1
        target: プロジェクト定義書
        from_scope: loop
        strategy: take_latest_success
        map_to: プロジェクト定義書#default
"""

# =========================================================================
# SECTION 2: TEST CLASS SPECIFICATION
# =========================================================================

class TestSc14SimpleApprovalGate:
    """
    [Scenario: Simple Approval Gate Physics]

    Intent:
        最少構成の Approval Gate (Loop + Serial) において、以下の物理挙動を検証する。
        1. 内部タスク (Worker) 完了後に、自律的に Approver ノードが生成されること。
        2. Approver による REJECT 時、Loop が物理的に次世代 (v2) を展開すること。
        3. Loop 完了後、ScopeResolve が正しく最新の成果物を特定すること。
    """

    # =========================================================================
    # SECTION 3: EXECUTION LOGIC
    # =========================================================================

    def test_run(self, simulator_cls):
        # --- 1. Setup ---
        ir_root = utils.load_ir_from_spec(SCENARIO_YAML)
        sim = simulator_cls(ir_root=ir_root, job_id=SCENARIO_ID)

        # --- 2. Action: Bootstrap Tick ---
        result = sim.tick()
        sim.dump_analysis_result(result, "01_bootstrap")

        # [Verification] 初回のWorkerが起動していること
        sim.assert_simulation_state(
            running=["v1/serial_0/worker_0"]
        )

        # --- 3. Action: Complete Worker (v1) ---
        result = sim.complete_node(path_suffix="v1/serial_0/worker_0")
        sim.dump_analysis_result(result, "02_v1_worker_done")

        # [Verification] 次のApproverが起動していること
        sim.assert_simulation_state(
            running=["v1/serial_0/approver_1"]
        )

        # --- 4. Action: Complete Approver (v1: 1st REJECT) ---
        # Harness側の修正により、初回は自動的にREJECTとなる
        result = sim.complete_node(path_suffix="v1/serial_0/approver_1")
        sim.dump_analysis_result(result, "03_v1_rejected")

        # [Verification] 否認によりv2のWorkerが起動していること
        sim.assert_node_status("v1/serial_0/approver_1", LifecycleStatus.COMPLETED, BusinessResult.REJECT)
        sim.assert_simulation_state(
            running=["v2/serial_0/worker_0"]
        )
        sim.assert_context("v2/serial_0/worker_0", "$LOOP", 2)

        # --- 5. Action: Complete v2 Worker & Approver (2nd SUCCESS) ---
        sim.complete_node(path_suffix="v2/serial_0/worker_0")
        
        # 2回目なので Harness は SUCCESS を返却
        result = sim.complete_node(path_suffix="v2/serial_0/approver_1")
        sim.dump_analysis_result(result, "04_v2_approved")

        # [Verification] Loopが正常完了し、ScopeResolveがデータ待ち状態であること
        sim.assert_node_status("root/serial_0/loop_0", LifecycleStatus.COMPLETED, BusinessResult.SUCCESS)
        sim.assert_node_status("root/serial_0/scope_resolve_1", LifecycleStatus.RUNNING)

        # --- 6. Action: Resolve Scope Data (Host Response) ---
        # 最新(v2)の成果物を「正」として解決
        result = sim.resolve_data(
            path_suffix="root/serial_0/scope_resolve_1",
            resolved_id="プロジェクト定義書#default/v2"
        )
        sim.dump_analysis_result(result, "05_scope_resolved")

        # --- 7. Final Verification ---
        sim.assert_simulation_state(
            running=[],
            completed=[
                "root/serial_0/loop_0",
                "root/serial_0/scope_resolve_1",
                "root/serial_0"
            ]
        )
        sim.assert_node_status("root/serial_0", LifecycleStatus.COMPLETED, BusinessResult.SUCCESS)