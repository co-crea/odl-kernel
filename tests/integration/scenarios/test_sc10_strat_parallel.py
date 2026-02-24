import pytest
from odl import utils
from odl_kernel.types import LifecycleStatus

# =========================================================================
# SECTION 1: SCENARIO DEFINITION
# =========================================================================

SCENARIO_ID = "sc10_strat_parallel"

SCENARIO_YAML = """
parallel:
  stack_path: root/parallel
  children:
    - worker: { stack_path: root/parallel/child_a, inputs: [], output: A }
    - worker: { stack_path: root/parallel/child_b, inputs: [], output: B }
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

        # [Verification] Batch Expansion (Macro State)
        # Parallel戦略により、1回のTickで全ての子(child_a, child_b)が一括生成され、
        # 同時にRUNNINGになっていることを検証する。
        # (Controlノードである親はRunningチェックの対象外だが、子はActionなので対象となる)
        sim.assert_simulation_state(
            running=[
                "root/parallel/child_a",
                "root/parallel/child_b"
            ]
        )

        # [Verification] Structural Integrity
        # 親ノード(Parallel)が正しく2つの子を持っているか確認
        # これにより、定義上の全ての子が漏れなく実体化されたことを保証する
        sim.assert_hierarchy(
            parent_suffix="root/parallel",
            expected_children_count=2
        )