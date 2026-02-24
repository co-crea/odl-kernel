import pytest
from odl import utils
from odl_kernel.types import LifecycleStatus, BusinessResult

# =========================================================================
# SECTION 1: SCENARIO DEFINITION
# =========================================================================

SCENARIO_ID = "sc02_smart_loop"

SCENARIO_YAML = """
loop:
  stack_path: root/loop
  count: 5
  break_on: success
  contents:
    worker:
      stack_path: root/loop/v{$LOOP}/worker
      agent: Reviewer
      mode: validate
      inputs: []
      output: Review
"""

# =========================================================================
# SECTION 2: TEST CLASS SPECIFICATION
# =========================================================================

class TestSc02SmartLoop:
    """
    [Scenario: Smart Validation Loop]

    Intent:
        Harnessの `complete_node` が、`validate` モードのノードに対して
        自動的に「1回目はREJECT」「2回目はSUCCESS」と振る舞うかを検証する。
        また、REJECT時にLoopが正しくv2を展開する（Deep Analyze）かを確認する。

    Structure:
        Root(Loop) -> Worker(Validate)
    """

    # =========================================================================
    # SECTION 3: EXECUTION LOGIC
    # =========================================================================

    def test_run(self, simulator_cls):
        # --- 1. Setup ---
        ir_root = utils.load_ir_from_spec(SCENARIO_YAML)
        sim = simulator_cls(ir_root=ir_root, job_id=SCENARIO_ID)

        # --- 2. Action: Bootstrap ---
        # v1 生成 -> Dispatch
        result = sim.tick()
        sim.dump_analysis_result(result, "01_bootstrap")

        # [Verification] Initial State
        # v1だけが動いていること
        sim.assert_simulation_state(
            running=["v1/worker"]
        )
        sim.assert_context("v1/worker", "$LOOP", 1)
        sim.assert_hierarchy("root/loop", expected_children_count=1)


        # --- 3. Action: Complete v1 (1st Attempt) ---
        # Validateモードなので、Harnessは自動的に REJECT とするはず
        # Deep Analyzeにより、v1完了 -> Loop判定(継続) -> v2生成 -> v2 Dispatch まで進む
        result_v1 = sim.complete_node(path_suffix="v1/worker")
        sim.dump_analysis_result(result_v1, "02_v1_complete")

        # [Verification] Retry Transition
        # v1は完了し、即座にv2が走っていること
        sim.assert_simulation_state(
            completed=["v1/worker"],
            running=["v2/worker"]
        )
        
        # v1の結果がREJECTであること
        sim.assert_node_status("v1/worker", LifecycleStatus.COMPLETED, BusinessResult.REJECT)

        # Loopは2世代目に入っていること
        sim.assert_hierarchy("root/loop", expected_children_count=2)
        sim.assert_context("v2/worker", "$LOOP", 2)


        # --- 4. Action: Complete v2 (2nd Attempt) ---
        # 2回目なので、Harnessは自動的に SUCCESS とするはず
        result_v2 = sim.complete_node(path_suffix="v2/worker")
        sim.dump_analysis_result(result_v2, "03_v2_complete")

        # [Verification] Break & Convergence
        # v2が成功したので、Loop全体が完了し、新たなRunningノードがないこと
        sim.assert_simulation_state(
            running=[],
            completed=["v2/worker", "root/loop"]
        )

        # [Verification] Negative Assertion (Break Logic)
        # break_on: success により、v3は生成されていないこと
        sim.assert_absent("v3/worker")

        # [Verification] Business Result
        # v2単体、およびLoop全体がSUCCESSであること
        sim.assert_node_status("v2/worker", LifecycleStatus.COMPLETED, BusinessResult.SUCCESS)
        sim.assert_node_status("root/loop", LifecycleStatus.COMPLETED, BusinessResult.SUCCESS)