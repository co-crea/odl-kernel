import pytest
from odl import utils
from odl_kernel.types import LifecycleStatus, CommandType, BusinessResult

# =========================================================================
# SECTION 1: SCENARIO DEFINITION
# Adopted from cocrea.5130.yml - Case 3_1_1 (Expansion IR)
# =========================================================================

SCENARIO_ID = "sc31_fanout_gate"

# Case 3_1_1: Parallel Fan-out containing Approval Gate
# Scenario: 中途採用の書類選考（面接官評価 -> 人事承認）
SCENARIO_YAML = """
serial:
  stack_path: root/serial_0
  children:
    # 1. Iterator Setup
    - iterator_init:
        stack_path: root/serial_0/iterator_init_0
        source: 応募者リスト:Applicants2025@stable
        item_key: ApplicantID

    # 2. Parallel Fan-out
    - iterate:
        stack_path: root/serial_0/iterate_1
        strategy: parallel
        contents:
          # === Approval Gate Expansion (Inside Iterator) ===
          serial:
            stack_path: root/serial_0/iterate_1/{$KEY}/serial_0
            children:
              - loop:
                  stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/loop_0
                  count: 10
                  break_on: success
                  contents:
                    serial:
                      stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/loop_0/v{$LOOP}/serial_0
                      children:
                        # 1. Worker Execution (Interviewer)
                        - worker:
                            stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/loop_0/v{$LOOP}/serial_0/worker_0
                            agent: Interviewer
                            mode: generate
                            inputs: 
                              - 採用基準:HiringCriteria@stable
                              - 履歴書.{$KEY}
                              # Feedback Injection
                              - 評価シート#default/{$KEY}/v{$LOOP-1}
                              - 評価シート__Review_HR_Manager#default/{$KEY}/v{$LOOP-1}
                            output: 評価シート#default/{$KEY}/v{$LOOP}

                        # 2. Approval Approver (HR_Manager)
                        - approver:
                            stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/loop_0/v{$LOOP}/serial_0/approver_1
                            agent: HR_Manager
                            inputs: 
                              - 評価シート#default/{$KEY}/v{$LOOP}
                              - 採用基準:HiringCriteria@stable
                              - 履歴書.{$KEY}
                            output: 評価シート__Review_HR_Manager#default/{$KEY}/v{$LOOP}

              # 3. Scope Resolution
              - scope_resolve:
                  stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/scope_resolve_1
                  target: 評価シート
                  from_scope: loop
                  strategy: take_latest_success
                  map_to: 評価シート#default/{$KEY}
"""

# =========================================================================
# SECTION 2: TEST CLASS SPECIFICATION
# =========================================================================

class TestSc31FanoutGate:
    """
    [Scenario: Fan-out with Nested Approval Gate (Case 3_1_1)]
    
    Intent:
        1. Parallel Independent Gates:
           各応募者(Applicant A, B)ごとに独立した承認プロセスが走ること。
           Aが承認待ちの間に、Bが差し戻し(Reject)を受けるといった非同期進行を検証。
        2. Deep ID Stacking:
           `root/.../{$KEY}/.../v{$LOOP}/...` という深い階層でのID解決と、
           `$KEY` (ApplicantID) と `$LOOP` (Gate Round) の変数が正しく注入されること。
        3. Feedback Loop Wiring:
           差し戻し後の再実行(v2)において、前回の評価シートとレビューコメントが入力として渡されること。
    """

    def test_run(self, simulator_cls):
        # --- 1. Setup ---
        ir_root = utils.load_ir_from_spec(SCENARIO_YAML)
        sim = simulator_cls(ir_root=ir_root, job_id=SCENARIO_ID)

        # --- 2. Action: Bootstrap ---
        res_boot = sim.tick()
        sim.dump_analysis_result(res_boot, "01_bootstrap")
        sim.dump_world_state("01_bootstrap_world")

        # --- 3. Action: Data Resolution ---
        # 2名の応募者 (A001, B002)
        mock_applicants = {
            "A001": {"ApplicantID": "A001", "Name": "Alice"},
            "B002": {"ApplicantID": "B002", "Name": "Bob"}
        }
        res_data = sim.resolve_data(path_suffix="iterator_init_0", items=mock_applicants)
        
        sim.dump_analysis_result(res_data, "02_data_resolved")
        sim.dump_world_state("02_data_resolved_world")

        # [Verification] Parallel Interview Start
        # 両名のInterviewerが同時に起動していること
        sim.assert_simulation_state(
            running=[
                "iterate_1/A001/serial_0/loop_0/v1/serial_0/worker_0",
                "iterate_1/B002/serial_0/loop_0/v1/serial_0/worker_0"
            ]
        )
        
        # [Verification] Context Injection Check
        worker_a = "iterate_1/A001/serial_0/loop_0/v1/serial_0/worker_0"
        sim.assert_context(worker_a, "$KEY", "A001")
        sim.assert_context(worker_a, "$LOOP", 1)
        sim.assert_wiring(worker_a, has_inputs=["履歴書.A001"])


        # ===========================================================
        # PHASE 1: Applicant A (Smooth Approval)
        # ===========================================================
        # A001: Interviewer -> Approver
        sim.complete_node(path_suffix="A001/serial_0/loop_0/v1/serial_0/worker_0")
        
        # [Verification] Approver Started
        sim.assert_simulation_state(
            running=[
                "iterate_1/A001/serial_0/loop_0/v1/serial_0/approver_1", # A: Waiting Approval
                "iterate_1/B002/serial_0/loop_0/v1/serial_0/worker_0"    # B: Still Interviewing
            ]
        )

        # A001: Approver (1st Attempt) -> REJECT (Harness Default)
        # Note: ApproverノードはHarness仕様で初回REJECTされるため、v2まで回す必要がある
        res_a_reject = sim.complete_node(path_suffix="A001/serial_0/loop_0/v1/serial_0/approver_1")
        sim.dump_analysis_result(res_a_reject, "03_a_v1_reject")

        # A001: v2 Start (Retry)
        sim.assert_simulation_state(
            running=[
                "iterate_1/A001/serial_0/loop_0/v2/serial_0/worker_0",
                "iterate_1/B002/serial_0/loop_0/v1/serial_0/worker_0"
            ]
        )

        # A001: v2 Interviewer -> Approver -> SUCCESS
        sim.complete_node(path_suffix="A001/serial_0/loop_0/v2/serial_0/worker_0")
        res_a_approve = sim.complete_node(path_suffix="A001/serial_0/loop_0/v2/serial_0/approver_1")
        
        sim.dump_analysis_result(res_a_approve, "04_a_approved")

        # [Verification] A001 Gate Closed, Scope Resolve Waiting
        sim.assert_node_status("iterate_1/A001/serial_0/loop_0", LifecycleStatus.COMPLETED, BusinessResult.SUCCESS)
        sim.assert_node_status("iterate_1/A001/serial_0/scope_resolve_1", LifecycleStatus.RUNNING)


        # ===========================================================
        # PHASE 2: Applicant B (Delayed Start & Rejection)
        # ===========================================================
        # B002: Interviewer -> Approver
        sim.complete_node(path_suffix="B002/serial_0/loop_0/v1/serial_0/worker_0")
        
        # B002: Approver (1st Attempt) -> REJECT
        # この操作で Loop が継続判定を行い、v2 を生成するはず
        res_b_reject = sim.complete_node(path_suffix="B002/serial_0/loop_0/v1/serial_0/approver_1")
        sim.dump_analysis_result(res_b_reject, "05_b_v1_reject")

        # [Debugging/Fix]
        # v2が見つからない場合、イベント処理後の時刻進行が必要な可能性があるため
        # 時間を進めてもう一度Analyzeを回す (Explicit Wait)
        target_v2_suffix = "iterate_1/B002/serial_0/loop_0/v2/serial_0/worker_0"
        
        if not sim._resolve_target_node(None, target_v2_suffix):
            print(f"[Info] Target node not found: {target_v2_suffix}. Ticking to stabilize physics...")
            sim.tick(delta_seconds=0.1)

        # [Verification] B002 Feedback Wiring (v2)
        # ここで確実に存在チェック
        worker_b_v2 = target_v2_suffix
        sim.assert_context(worker_b_v2, "$LOOP", 2)
        
        sim.assert_wiring(
            worker_b_v2,
            has_inputs=[
                "履歴書.B002",
                "評価シート#default/B002/v1",
                "評価シート__Review_HR_Manager#default/B002/v1"
            ]
        )

        # B002: v2 Interviewer -> Approver -> SUCCESS
        sim.complete_node(path_suffix="B002/serial_0/loop_0/v2/serial_0/worker_0")
        sim.complete_node(path_suffix="B002/serial_0/loop_0/v2/serial_0/approver_1")

        # [Verification] B002 Gate Closed
        sim.assert_node_status("iterate_1/B002/serial_0/loop_0", LifecycleStatus.COMPLETED, BusinessResult.SUCCESS)
        sim.assert_node_status("iterate_1/B002/serial_0/scope_resolve_1", LifecycleStatus.RUNNING)


        # ===========================================================
        # PHASE 3: Final Resolution
        # ===========================================================
        
        # Host Response: A001
        sim.resolve_data(
            path_suffix="A001/serial_0/scope_resolve_1",
            resolved_id="評価シート#default/A001/v2"
        )
        
        # Host Response: B002
        res_final = sim.resolve_data(
            path_suffix="B002/serial_0/scope_resolve_1",
            resolved_id="評価シート#default/B002/v2"
        )

        sim.dump_analysis_result(res_final, "06_all_done")
        sim.dump_world_state("06_all_done_world")

        # [Verification] Final State
        sim.assert_simulation_state(
            running=[],
            completed=[
                "iterate_1/A001/serial_0",
                "iterate_1/B002/serial_0",
                "iterate_1",
                "root/serial_0"
            ]
        )