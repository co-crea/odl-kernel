import pytest
from odl import utils
from odl_kernel.types import LifecycleStatus, CommandType, BusinessResult

# =========================================================================
# SECTION 1: SCENARIO DEFINITION
# =========================================================================

SCENARIO_ID = "sc11_generate_team"

SCENARIO_YAML = """
serial:
  stack_path: root/serial_0
  children:
    - loop:
        stack_path: root/serial_0/loop_0
        count: 3
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
                    - プロジェクト定義書__Review_SecuritySpecialist#default/v{$LOOP-1}
                  output: プロジェクト定義書#default/v{$LOOP}
              - parallel:
                  stack_path: root/serial_0/loop_0/v{$LOOP}/serial_0/parallel_1
                  children:
                    - worker:
                        stack_path: root/serial_0/loop_0/v{$LOOP}/serial_0/parallel_1/worker_0
                        agent: SecuritySpecialist
                        mode: validate
                        inputs:
                          - 全社規定:Rules01@stable
                          - 市場レポート:Mkt05@latest
                          - プロジェクト定義書#default/v{$LOOP}
                        output: プロジェクト定義書__Review_SecuritySpecialist#default/v{$LOOP}
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

class TestSc10StratParallel:
    """
    [Scenario: Parallel Strategy Physics]

    Intent:
        Parallelノードにおいて、定義された全ての子ノードが
        1回のTick（Deep Analyze）で一括生成（Batch Creation）されることを検証する。
    """

    # =========================================================================
    # SECTION 3: EXECUTION LOGIC
    # =========================================================================

    def test_run(self, simulator_cls):
        # --- 1. Setup ---
        ir_root = utils.load_ir_from_spec(SCENARIO_YAML)
        sim = simulator_cls(ir_root=ir_root, job_id=SCENARIO_ID)

        # --- 2. Action: Bootstrap ---
        result = sim.tick()
        sim.dump_analysis_result(result, "01_bootstrap")

        # [Verification] Lazy Expansion (v1のみ生成)
        sim.assert_simulation_state(
            running=["v1/serial_0/worker_0"]
        )
        sim.assert_hierarchy("root/serial_0/loop_0", expected_children_count=1)
        sim.assert_context("v1/serial_0/worker_0", "$LOOP", 1)


        # --- 3. Action: Complete v1 Generator ---
        result = sim.complete_node(path_suffix="v1/serial_0/worker_0")
        sim.dump_analysis_result(result, "02_v1_gen_done")

        # [Verification] Flow Progression -> Validator(Parallel)起動
        sim.assert_simulation_state(
            completed=["v1/serial_0/worker_0"],
            running=["v1/serial_0/parallel_1/worker_0"]
        )


        # --- 4. Action: Complete v1 Validator (REJECT) ---
        # Validator(REJECT) -> Loop判定(Next) -> v2生成
        result = sim.complete_node(path_suffix="v1/serial_0/parallel_1/worker_0")
        sim.dump_analysis_result(result, "03_v1_val_reject")

        # [Verification] v2 Generator Start
        sim.assert_simulation_state(
            completed=["v1/serial_0/parallel_1/worker_0"],
            running=["v2/serial_0/worker_0"]
        )
        sim.assert_context("v2/serial_0/worker_0", "$LOOP", 2)


        # --- 5. Action: Complete v2 Generator ---
        result = sim.complete_node(path_suffix="v2/serial_0/worker_0")
        sim.dump_analysis_result(result, "04_v2_gen_done")

        sim.assert_simulation_state(
            completed=["v2/serial_0/worker_0"],
            running=["v2/serial_0/parallel_1/worker_0"]
        )


        # --- 6. Action: Complete v2 Validator (SUCCESS) ---
        # Validator(SUCCESS) -> Loop判定(Break) -> Loop(COMPLETED) -> ScopeResolve(RUNNING/WAITING)
        result = sim.complete_node(path_suffix="v2/serial_0/parallel_1/worker_0")
        sim.dump_analysis_result(result, "05_v2_val_success")

        # [Verification] Scope Resolve Waiting
        # Loopは完了したが、ScopeResolveはデータ解決待ちでRUNNING状態であること
        sim.assert_node_status("root/serial_0/loop_0", LifecycleStatus.COMPLETED, BusinessResult.SUCCESS)
        sim.assert_node_status("root/serial_0/scope_resolve_1", LifecycleStatus.RUNNING)
        
        # [Physics Verification] Command Check
        # KernelがHostに対して解決要求(REQUIRE_DATA)を出していること
        require_cmd = next((c for c in result.commands if c.type == CommandType.REQUIRE_DATA), None)
        assert require_cmd is not None
        assert require_cmd.payload["request_type"] == "RESOLVE_SCOPE"


        # --- 7. Action: Resolve Scope Data (Host Response) ---
        # Hostが履歴から「v2の成果物が最新である」と特定し、IDを返す
        # v2 Output: "プロジェクト定義書#default/v2"
        result = sim.resolve_data(
            path_suffix="root/serial_0/scope_resolve_1",
            resolved_id="プロジェクト定義書#default/v2"
        )
        sim.dump_analysis_result(result, "06_scope_resolved")

        # [Verification] Final Convergence
        # ScopeResolveも完了し、ジョブ全体が完了していること
        sim.assert_simulation_state(
            running=[],
            completed=[
                "root/serial_0/loop_0",
                "root/serial_0/scope_resolve_1",
                "root/serial_0"
            ]
        )
        
        # [Verification] Resolved Output
        # ScopeResolveの出力が、渡したIDになっていること
        scope_node = sim.nodes[require_cmd.target_node_id]
        assert scope_node.lifecycle_status == LifecycleStatus.COMPLETED
        assert scope_node.runtime_context.output_aggregation[-1] == "プロジェクト定義書#default/v2"