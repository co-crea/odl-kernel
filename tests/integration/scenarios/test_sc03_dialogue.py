import pytest
from odl import utils
from odl_kernel.types import LifecycleStatus, BusinessResult

# =========================================================================
# SECTION 1: SCENARIO DEFINITION
# =========================================================================

SCENARIO_ID = "sc03_dialogue"

SCENARIO_YAML = """
dialogue:
  stack_path: root/dialogue
  agent: User
  inputs: []
  output: Chat
"""

# =========================================================================
# SECTION 2: TEST CLASS SPECIFICATION
# =========================================================================

class TestSc03Dialogue:
    """
    [Scenario: Dialogue Node Behavior]

    Intent:
        Dialogueノードが正常にDispatchされ、完了時には
        BusinessResult.NONE（成果物なしのSuccess扱い）となることを検証する。

    Structure:
        Root(Dialogue)
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

        # [Verification] Running State
        # Dialogueノードが起動していること
        sim.assert_simulation_state(
            running=["dialogue"]
        )

        # --- 3. Action: Complete ---
        # DialogueはHarnessにより自動的に承認(NONE)される
        result = sim.complete_node(path_suffix="dialogue")
        sim.dump_analysis_result(result, "02_complete")

        # [Verification] Final State
        # Dialogueが完了し、他に動いているノードがないこと
        sim.assert_simulation_state(
            running=[],
            completed=["dialogue"]
        )

        # [Verification] Result Check
        # 期待値: ステータスはCOMPLETED, 結果はNONEであること
        sim.assert_node_status("dialogue", LifecycleStatus.COMPLETED, BusinessResult.NONE)