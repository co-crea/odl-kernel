import pytest
from odl import utils
from odl_kernel.types import LifecycleStatus, CommandType, BusinessResult

# =========================================================================
# SECTION 1: SCENARIO DEFINITION
# Adopted from cocrea.5120.yml - Case 2_3_2 (Expansion IR)
# =========================================================================

SCENARIO_ID = "sc23_fanout_serial_complex"

# Case 2_3_2: Serial Fan-out with Generate Team, Ensemble, and Context Relay
# Scenario: 全社業務改善のリレープロジェクト
# 1. Generate Team: 支店ごとに改善計画を策定（過去の他支店計画 $HISTORY を参照）
# 2. Ensemble: 計画に基づき、周知ポスターを複数案作成
# 3. Worker: 進捗をリレー報告（前の支店の報告 $PREV を参照）
SCENARIO_YAML = """
serial:
  stack_path: root/serial_0
  children:
    - iterator_init:
        stack_path: root/serial_0/iterator_init_0
        source: 支店リスト:Branches@stable
        item_key: BranchID
    - iterate:
        stack_path: root/serial_0/iterate_1
        strategy: serial
        contents:
          serial:
            stack_path: root/serial_0/iterate_1/{$KEY}/serial_0
            children:
              - serial:
                  stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/serial_0
                  children:
                    - loop:
                        stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/serial_0/loop_0
                        count: 3
                        break_on: success
                        contents:
                          serial:
                            stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/serial_0/loop_0/v{$LOOP}/serial_0
                            children:
                              - worker:
                                  stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/serial_0/loop_0/v{$LOOP}/serial_0/worker_0
                                  agent: KaizenLead
                                  mode: generate
                                  inputs:
                                    - 支店データ.{$KEY}
                                    - 改善計画書#{$HISTORY} # 解決後の兄リスト(蓄積)
                                    - 改善計画書#default/{$KEY}/v{$LOOP-1}
                                    - 改善計画書__Review_BranchMgr#default/{$KEY}/v{$LOOP-1}
                                    - 改善計画書__Review_HQ_QA#default/{$KEY}/v{$LOOP-1}
                                  output: 改善計画書#default/{$KEY}/v{$LOOP}
                              - parallel:
                                  stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/serial_0/loop_0/v{$LOOP}/serial_0/parallel_1
                                  children:
                                    - worker:
                                        stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/serial_0/loop_0/v{$LOOP}/serial_0/parallel_1/worker_0
                                        agent: BranchMgr
                                        mode: validate
                                        inputs: 
                                          - 支店データ.{$KEY}
                                          - 改善計画書#{$HISTORY}
                                          - 改善計画書#default/{$KEY}/v{$LOOP} # 検証対象
                                        output: 改善計画書__Review_BranchMgr#default/{$KEY}/v{$LOOP}
                                    - worker:
                                        stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/serial_0/loop_0/v{$LOOP}/serial_0/parallel_1/worker_1
                                        agent: HQ_QA
                                        mode: validate
                                        inputs: 
                                          - 支店データ.{$KEY}
                                          - 改善計画書#{$HISTORY}
                                          - 改善計画書#default/{$KEY}/v{$LOOP}
                                        output: 改善計画書__Review_HQ_QA#default/{$KEY}/v{$LOOP}
                    - scope_resolve:
                        stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/serial_0/scope_resolve_1
                        target: 改善計画書
                        from_scope: loop
                        strategy: take_latest_success
                        map_to: 改善計画書#default/{$KEY}
              - serial:
                  stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/serial_1
                  children:
                    - parallel:
                        stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/serial_1/parallel_0
                        children:
                          - worker:
                              stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/serial_1/parallel_0/worker_0
                              agent: StaffA
                              mode: generate
                              inputs: 
                                - 改善計画書#default/{$KEY}
                              output: _周知ポスター#default/{$KEY}/StaffA/1
                          - worker:
                              stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/serial_1/parallel_0/worker_1
                              agent: StaffA
                              mode: generate
                              inputs: 
                                - 改善計画書#default/{$KEY}
                              output: _周知ポスター#default/{$KEY}/StaffA/2
                          - worker:
                              stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/serial_1/parallel_0/worker_2
                              agent: StaffB
                              mode: generate
                              inputs: 
                                - 改善計画書#default/{$KEY}
                              output: _周知ポスター#default/{$KEY}/StaffB/1
                          - worker:
                              stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/serial_1/parallel_0/worker_3
                              agent: StaffB
                              mode: generate
                              inputs: 
                                - 改善計画書#default/{$KEY}
                              output: _周知ポスター#default/{$KEY}/StaffB/2
                    - worker:
                        stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/serial_1/worker_1
                        agent: Leader
                        mode: generate
                        inputs:
                          - 改善計画書#default/{$KEY}
                          - _周知ポスター#default/{$KEY}/StaffA/1
                          - _周知ポスター#default/{$KEY}/StaffA/2
                          - _周知ポスター#default/{$KEY}/StaffB/1
                          - _周知ポスター#default/{$KEY}/StaffB/2
                        output: 周知ポスター#default/{$KEY}
              - worker:
                  stack_path: root/serial_0/iterate_1/{$KEY}/serial_0/worker_2
                  agent: Admin
                  mode: generate
                  inputs:
                    - 周知ポスター#default/{$KEY}
                    - 進捗リレー報告#{$PREV} # Serial Relay
                  output: 進捗リレー報告#default/{$KEY}
"""

# =========================================================================
# SECTION 2: TEST CLASS SPECIFICATION
# =========================================================================

class TestSc23FanoutSerialComplex:
    """
    [Scenario: Serial Fan-out with Complex Internal Logic (Case 2_3_2)]
    
    Intent:
        1. Serial Sequence: 支店A -> 支店B の順で厳格に実行されること。
        2. History Context: 支店Bの実行時、$HISTORY に支店Aの計画が含まれていること。
        3. Relay Context: 支店BのStep3実行時、$PREV が支店Aの報告を指していること。
        4. Internal Generate Team: 支店Aの中で、Generate -> Reject -> Retry のループが正常に回ること。
        5. Internal Ensemble: 支店Aの中で、計画確定後にポスター制作の発散・収束が行われること。
    """

    def test_run(self, simulator_cls):
        # --- 1. Setup ---
        ir_root = utils.load_ir_from_spec(SCENARIO_YAML)
        sim = simulator_cls(ir_root=ir_root, job_id=SCENARIO_ID)

        # --- 2. Action: Bootstrap & Data Resolution ---
        res_boot = sim.tick()
        
        # 支店データ (Branch A, Branch B)
        mock_branches = {
            "BranchA": {"BranchID": "BranchA", "Name": "Tokyo"},
            "BranchB": {"BranchID": "BranchB", "Name": "Osaka"}
        }
        res_data = sim.resolve_data(path_suffix="iterator_init_0", items=mock_branches)
        
        sim.dump_analysis_result(res_data, "01_branch_a_start")
        sim.dump_world_state("01_branch_a_start_world")

        # [Verification] Branch A Started (Lazy Expansion)
        # BranchAのGenerate Team (KaizenLead) が起動していること。BranchBはまだ影も形もないこと。
        kaizen_a_v1 = "iterate_1/BranchA/serial_0/serial_0/loop_0/v1/serial_0/worker_0"
        sim.assert_simulation_state(
            running=[kaizen_a_v1]
        )
        sim.assert_absent("iterate_1/BranchB")

        # [Verification] History Check (First Item)
        # 初回なので $HISTORY は空、またはフィルタリングされて消えていること
        sim.assert_wiring(kaizen_a_v1, no_inputs=["改善計画書#{$HISTORY}"])


        # ===========================================================
        # PHASE 1: Branch A - Internal Logic
        # ===========================================================

        # --- Step 1: Generate Team Loop (Reject -> Success) ---
        # 1-1. KaizenLead (v1) -> Validators (v1) -> REJECT
        sim.complete_node(path_suffix="BranchA/serial_0/serial_0/loop_0/v1/serial_0/worker_0")
        sim.complete_node(path_suffix="BranchA/serial_0/serial_0/loop_0/v1/serial_0/parallel_1/worker_0") # Val1
        res_a_v1_fail = sim.complete_node(path_suffix="BranchA/serial_0/serial_0/loop_0/v1/serial_0/parallel_1/worker_1") # Val2
        
        sim.dump_analysis_result(res_a_v1_fail, "02_branch_a_v1_reject")

        # 1-2. Retry (v2) -> SUCCESS
        # v2 Generator起動確認
        kaizen_a_v2 = "iterate_1/BranchA/serial_0/serial_0/loop_0/v2/serial_0/worker_0"
        sim.assert_simulation_state(running=[kaizen_a_v2])
        sim.assert_context(kaizen_a_v2, "$LOOP", 2)
        
        sim.complete_node(path_suffix="BranchA/serial_0/serial_0/loop_0/v2/serial_0/worker_0")
        sim.complete_node(path_suffix="BranchA/serial_0/serial_0/loop_0/v2/serial_0/parallel_1/worker_0")
        # Loop Exit Trigger
        sim.complete_node(path_suffix="BranchA/serial_0/serial_0/loop_0/v2/serial_0/parallel_1/worker_1")
        
        # 1-3. Scope Resolve (Host)
        # チーム検討完了 -> 計画確定
        res_a_team_done = sim.resolve_data(
            path_suffix="BranchA/serial_0/serial_0/scope_resolve_1",
            resolved_id="改善計画書#default/BranchA/v2"
        )
        sim.dump_analysis_result(res_a_team_done, "03_branch_a_plan_fixed")


        # --- Step 2: Ensemble (Poster Creation) ---
        # 計画確定を受け、Ensemble (Parallel Generators) が起動していること
        sim.assert_simulation_state(
            running=[
                "iterate_1/BranchA/serial_0/serial_1/parallel_0/worker_0", # StaffA 1
                "iterate_1/BranchA/serial_0/serial_1/parallel_0/worker_1", # StaffA 2
                "iterate_1/BranchA/serial_0/serial_1/parallel_0/worker_2", # StaffB 1
                "iterate_1/BranchA/serial_0/serial_1/parallel_0/worker_3", # StaffB 2
            ]
        )
        
        # Parallel Execution
        sim.complete_node(path_suffix="BranchA/serial_0/serial_1/parallel_0/worker_0")
        sim.complete_node(path_suffix="BranchA/serial_0/serial_1/parallel_0/worker_1")
        sim.complete_node(path_suffix="BranchA/serial_0/serial_1/parallel_0/worker_2")
        sim.complete_node(path_suffix="BranchA/serial_0/serial_1/parallel_0/worker_3")

        # Consolidation (Leader)
        leader_a = "iterate_1/BranchA/serial_0/serial_1/worker_1"
        sim.assert_wiring(leader_a, has_inputs=[
            "改善計画書#default/BranchA",
            "_周知ポスター#default/BranchA/StaffA/1",
            "_周知ポスター#default/BranchA/StaffB/1"
        ])
        sim.complete_node(path_suffix="BranchA/serial_0/serial_1/worker_1")


        # --- Step 3: Relay Worker (Admin) ---
        admin_a = "iterate_1/BranchA/serial_0/worker_2"
        sim.assert_simulation_state(running=[admin_a])
        
        # 初回なので $PREV (進捗リレー報告) は存在しないはず
        sim.assert_wiring(admin_a, no_inputs=["進捗リレー報告#{$PREV}"])
        
        res_a_done = sim.complete_node(path_suffix="BranchA/serial_0/worker_2")
        sim.dump_analysis_result(res_a_done, "04_branch_a_complete")
        sim.dump_world_state("04_branch_a_complete_world")


        # ===========================================================
        # PHASE 2: Branch B - Serial Progression
        # ===========================================================
        
        # [Verification] Branch B Started
        # A完了を受けて、BのKaizenLeadが起動していること
        kaizen_b_v1 = "iterate_1/BranchB/serial_0/serial_0/loop_0/v1/serial_0/worker_0"
        sim.assert_simulation_state(running=[kaizen_b_v1])

        # [Verification] History Injection ($HISTORY)
        # Aの成果物（計画書）が見えているか？
        # Logic: 改善計画書#{$HISTORY} -> ["改善計画書#default/BranchA"]
        sim.assert_wiring(
            kaizen_b_v1,
            has_inputs=["改善計画書#default/BranchA"]
        )

        # --- B: Generate Team (Cycle v1 -> v2) ---
        # Note: Harnessの仕様により、BranchBも初回は必ずREJECTされるため、
        # v1(Reject) -> v2(Success) のサイクルを実行する。

        # v1: Gen -> Val -> Reject
        sim.complete_node(path_suffix="BranchB/serial_0/serial_0/loop_0/v1/serial_0/worker_0")
        sim.complete_node(path_suffix="BranchB/serial_0/serial_0/loop_0/v1/serial_0/parallel_1/worker_0")
        sim.complete_node(path_suffix="BranchB/serial_0/serial_0/loop_0/v1/serial_0/parallel_1/worker_1") # v2 Spawned

        # v2: Gen -> Val -> Success
        sim.complete_node(path_suffix="BranchB/serial_0/serial_0/loop_0/v2/serial_0/worker_0")
        sim.complete_node(path_suffix="BranchB/serial_0/serial_0/loop_0/v2/serial_0/parallel_1/worker_0")
        
        # 最後のValidator完了 -> Loop完了 -> ScopeResolve起動
        sim.complete_node(path_suffix="BranchB/serial_0/serial_0/loop_0/v2/serial_0/parallel_1/worker_1")

        # [Verification] Wait for Scope Resolve
        sim.assert_node_status("BranchB/serial_0/serial_0/scope_resolve_1", LifecycleStatus.RUNNING)
        
        sim.resolve_data(
            path_suffix="BranchB/serial_0/serial_0/scope_resolve_1",
            resolved_id="改善計画書#default/BranchB/v2"
        )

        # --- B: Ensemble (Fast Forward) ---
        # Staff達を一気に完了
        sim.complete_node(path_suffix="BranchB/serial_0/serial_1/parallel_0/worker_0")
        sim.complete_node(path_suffix="BranchB/serial_0/serial_1/parallel_0/worker_1")
        sim.complete_node(path_suffix="BranchB/serial_0/serial_1/parallel_0/worker_2")
        sim.complete_node(path_suffix="BranchB/serial_0/serial_1/parallel_0/worker_3")
        # Leader完了
        sim.complete_node(path_suffix="BranchB/serial_0/serial_1/worker_1")


        # --- B: Relay Worker (Admin) ---
        admin_b = "iterate_1/BranchB/serial_0/worker_2"
        sim.assert_simulation_state(running=[admin_b])

        # [Verification] Relay Injection ($PREV)
        # AのAdminが出した「進捗リレー報告」が見えているか？
        # Logic: 進捗リレー報告#{$PREV} -> "進捗リレー報告#default/BranchA"
        sim.assert_wiring(
            admin_b,
            has_inputs=["進捗リレー報告#default/BranchA"]
        )

        res_final = sim.complete_node(path_suffix="BranchB/serial_0/worker_2")
        sim.dump_analysis_result(res_final, "05_all_done")
        sim.dump_world_state("05_all_done_world")

        # [Verification] Final State
        sim.assert_simulation_state(
            running=[],
            completed=[
                "iterate_1/BranchA/serial_0",
                "iterate_1/BranchB/serial_0",
                "iterate_1",
                "root/serial_0"
            ]
        )