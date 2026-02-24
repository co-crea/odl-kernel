import pytest
from odl import utils
from odl_kernel import NodeInspector
from odl_kernel.types import LifecycleStatus, CommandType, BusinessResult

# =========================================================================
# SECTION 1: SCENARIO DEFINITION
# =========================================================================

SCENARIO_ID = "sc12_generate_team_2"

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
                    - プロジェクト定義書__Review_TechnicalLead#default/v{$LOOP-1}
                    - プロジェクト定義書__Review_ProductOwner#default/v{$LOOP-1}
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
                    - worker:
                        stack_path: root/serial_0/loop_0/v{$LOOP}/serial_0/parallel_1/worker_1
                        agent: TechnicalLead
                        mode: validate
                        inputs:
                          - 全社規定:Rules01@stable
                          - 市場レポート:Mkt05@latest
                          - プロジェクト定義書#default/v{$LOOP}
                        output: プロジェクト定義書__Review_TechnicalLead#default/v{$LOOP}
                    - worker:
                        stack_path: root/serial_0/loop_0/v{$LOOP}/serial_0/parallel_1/worker_2
                        agent: ProductOwner
                        mode: validate
                        inputs:
                          - 全社規定:Rules01@stable
                          - 事業戦略:SecA@latest
                          - 市場レポート:Mkt05@latest
                          - プロジェクト定義書#default/v{$LOOP}
                        output: プロジェクト定義書__Review_ProductOwner#default/v{$LOOP}
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

class TestSc12GenerateTeam:
    """
    [Scenario: Generate Team with Loop & Parallel]

    Intent:
        1. Parallelノードの一括生成（Batch Creation）の検証
        2. Harnessによる自動応答（Validate 1回目Reject -> 2回目Success）の遷移検証
        3. [New] Wiringの動的解決とフィルタリング（$LOOP-1）の検証
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

        # [Verification] 1. Bootstrap State
        sim.assert_simulation_state(
            running=["v1/serial_0/worker_0"]
        )
        sim.assert_context("v1/serial_0/worker_0", "$LOOP", 1)

        # v1は初回なので False になるべき
        v1_node = sim._resolve_target_node(None, "v1/serial_0/worker_0")
        assert v1_node is not None        
        is_retry_v1 = NodeInspector.is_recreation_by_input(v1_node)
        print(f"\n[Inspector Check] v1 Node ({v1_node.stack_path}): Is Retry? -> {is_retry_v1}")
        assert is_retry_v1 is False, "v1 should be INITIAL creation"


        # --- 3. Action: Complete v1 Generator ---
        result = sim.complete_node(path_suffix="v1/serial_0/worker_0")
        sim.dump_analysis_result(result, "02_v1_gen_done")

        # [Verification] 2. Parallel Batch Expansion
        sim.assert_simulation_state(
            completed=["v1/serial_0/worker_0"],
            running=[
                "v1/serial_0/parallel_1/worker_0",
                "v1/serial_0/parallel_1/worker_1",
                "v1/serial_0/parallel_1/worker_2"
            ]
        )

        # =========================================================================
        # [Verification] New Feature: is_validation_target Check
        # =========================================================================
        # SecuritySpecialist (Validator) のノードを取得
        val_node = sim._resolve_target_node(None, "v1/serial_0/parallel_1/worker_0")
        assert val_node is not None

        print(f"\n[Inspector Check] Validator Node: {val_node.stack_path}")
        print(f"  Inputs: {val_node.wiring.inputs}")
        print(f"  Output: {val_node.wiring.output}")

        # Case A: 検証対象 (Target) -> True
        # Generatorの成果物であり、出力名(Target__Review_Agent)のTarget部分と一致するもの
        target_id = "プロジェクト定義書#default/v1"
        is_target = NodeInspector.is_validation_target(val_node, target_id)
        print(f"  Check '{target_id}' -> {is_target}")
        assert is_target is True, f"'{target_id}' SHOULD be identified as validation target"

        # Case B: 参照資料 (Reference) -> False
        # inputには含まれているが、出力名のTarget部分とは一致しないもの
        ref_id = "全社規定:Rules01@stable"
        is_ref = NodeInspector.is_validation_target(val_node, ref_id)
        print(f"  Check '{ref_id}' -> {is_ref}")
        assert is_ref is False, f"'{ref_id}' should NOT be identified as validation target"

        # Case C: 無関係なID -> False
        random_id = "UnknownDoc#v1"
        assert NodeInspector.is_validation_target(val_node, random_id) is False
        # =========================================================================

        # --- 4. Action: Complete v1 Validators (REJECT Loop) ---
        sim.complete_node(path_suffix="v1/serial_0/parallel_1/worker_0") # Reject 1
        sim.complete_node(path_suffix="v1/serial_0/parallel_1/worker_1") # Reject 2
        result = sim.complete_node(path_suffix="v1/serial_0/parallel_1/worker_2") # Reject 3 -> v2 Spawn
        sim.dump_analysis_result(result, "03_v1_val_all_reject")

        # [Verification] 3. v2 Generation
        sim.assert_simulation_state(
            running=["v2/serial_0/worker_0"]
        )
        sim.assert_context("v2/serial_0/worker_0", "$LOOP", 2)

        # v2は v1 の成果物を入力に持つため True になるべき
        v2_node = sim._resolve_target_node(None, "v2/serial_0/worker_0")
        assert v2_node is not None
        print(f"  Inputs: {v2_node.wiring.inputs}")
        is_retry_v2 = NodeInspector.is_recreation_by_input(v2_node)
        print(f"[Inspector Check] v2 Node ({v2_node.stack_path}): Is Retry? -> {is_retry_v2}")
        assert is_retry_v2 is True, "v2 should be RE-creation (Retry)"


        # --- 5. Action: Complete v2 Generator ---
        result = sim.complete_node(path_suffix="v2/serial_0/worker_0")
        sim.assert_simulation_state(
            running=[
                "v2/serial_0/parallel_1/worker_0",
                "v2/serial_0/parallel_1/worker_1",
                "v2/serial_0/parallel_1/worker_2"
            ]
        )


        # --- 6. Action: Complete v2 Validators (SUCCESS) ---
        sim.complete_node(path_suffix="v2/serial_0/parallel_1/worker_0")
        sim.complete_node(path_suffix="v2/serial_0/parallel_1/worker_1")
        # 最後のValidatorが完了 -> Loop完了 -> ScopeResolve起動(Wait)
        result = sim.complete_node(path_suffix="v2/serial_0/parallel_1/worker_2")
        sim.dump_analysis_result(result, "04_v2_all_success")

        # [Verification] 4. Scope Resolve Waiting
        sim.assert_node_status("v2/serial_0/parallel_1", LifecycleStatus.COMPLETED, BusinessResult.SUCCESS)
        sim.assert_node_status("root/serial_0/loop_0", LifecycleStatus.COMPLETED, BusinessResult.SUCCESS)
        
        # ScopeResolveはまだ完了せず、データ待ちであること
        sim.assert_node_status("root/serial_0/scope_resolve_1", LifecycleStatus.RUNNING)
        sim.assert_absent("v3/serial_0/worker_0")


        # --- 7. Action: Resolve Scope Data (Host Response) ---
        # v2の成果物IDで解決
        result = sim.resolve_data(
            path_suffix="root/serial_0/scope_resolve_1",
            resolved_id="プロジェクト定義書#default/v2"
        )
        sim.dump_analysis_result(result, "05_scope_resolved")

        # [Verification] 5. Final State
        sim.assert_simulation_state(
            running=[],
            completed=["root/serial_0"]
        )
        sim.assert_node_status("root/serial_0/scope_resolve_1", LifecycleStatus.COMPLETED, BusinessResult.SUCCESS)