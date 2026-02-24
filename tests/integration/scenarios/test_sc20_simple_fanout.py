import pytest
from odl import utils
from odl_kernel.types import LifecycleStatus, CommandType, BusinessResult

# =========================================================================
# SECTION 1: SCENARIO DEFINITION
# 添付資料 cocrea.5120.yml: Case 2_2_1 (単体fan_out) に基づく
# =========================================================================

SCENARIO_ID = "sc20_simple_fanout"

SCENARIO_YAML = """
serial:
  stack_path: root/serial_0
  children:
    - iterator_init:
        stack_path: root/serial_0/iterator_init_0
        source: "会員リスト:Members2025@stable"
        item_key: "MemberID"
    - iterate:
        stack_path: root/serial_0/iterate_1
        strategy: parallel
        contents:
          worker:
            stack_path: root/serial_0/iterate_1/{$KEY}/worker_0
            agent: Marketer
            mode: generate
            inputs: 
              - "キャンペーン要項:CampRules@stable"
              - "会員情報.{$KEY}"
            output: "個別DMドラフト#default/{$KEY}"
"""

# =========================================================================
# SECTION 2: TEST CLASS SPECIFICATION
# =========================================================================

class TestSc20SimpleFanout:
    """
    [Scenario: Simple Parallel Fan-out]

    Intent:
        fan_outプリミティブの展開プロセスを検証する。
        1. iterator_init が実行され、Hostにデータ解決 (REQUIRE_DATA) を求めること。
        2. データ解決後、iterate が strategy=parallel に基づき、全要素を一括展開すること。
        3. 各子ノードに $KEY, $ITEM が正しく注入され、IDが解決されていること。
    """

    def test_run(self, simulator_cls):
        # --- 1. Setup ---
        ir_root = utils.load_ir_from_spec(SCENARIO_YAML)
        sim = simulator_cls(ir_root=ir_root, job_id=SCENARIO_ID)

        # --- 2. Action: Bootstrap ---
        # 期待値: iterator_init_0 が生成され、RUNNINGになる
        result = sim.tick()
        sim.dump_analysis_result(result, "01_bootstrap")

        sim.assert_node_status("iterator_init_0", LifecycleStatus.RUNNING)
        
        # [Physics Check] KernelがHostへデータ解決を要求しているか
        require_cmd = next((c for c in result.commands if c.type == CommandType.REQUIRE_DATA), None)
        assert require_cmd is not None
        assert require_cmd.payload["request_type"] == "RESOLVE_ITERATOR_SOURCE"

        # --- 3. Action: Resolve Iterator Data ---
        # Host(Simulator)がリストデータを返す
        # 3名分の会員データを注入
        mock_members = [
            {"MemberID": "M001", "name": "Alice"},
            {"MemberID": "M002", "name": "Bob"},
            {"MemberID": "M003", "name": "Charlie"}
        ]
        mock_members_map = {m["MemberID"]: m for m in mock_members}
        result = sim.resolve_data(
            path_suffix="iterator_init_0",
            items=mock_members_map # 物理法則が期待する形式
        )

        sim.dump_analysis_result(result, "02_data_resolved")

        # [Verification] iterator_init完了 -> iterate開始 -> 一括展開(Parallel)
        # Deep Analyzeにより、データ解決から子ノードのDispatchまで一気に進むはず
        sim.assert_node_status("iterator_init_0", LifecycleStatus.COMPLETED)
        
        # 3つのWorkerが同時に動いていること
        expected_workers = [
            "iterate_1/M001/worker_0",
            "iterate_1/M002/worker_0",
            "iterate_1/M003/worker_0"
        ]
        sim.assert_simulation_state(running=expected_workers)

        # --- 4. Action: Context & Wiring Check ---
        # 2人目の会員(Bob)のノードを詳しく調査
        bob_node_path = "iterate_1/M002/worker_0"
        sim.assert_context(bob_node_path, "$KEY", "M002")
        sim.assert_context(bob_node_path, "$ITEM", {"MemberID": "M002", "name": "Bob"})
        sim.assert_wiring(
            bob_node_path,
            has_inputs=[
                "キャンペーン要項:CampRules@stable",
                "会員情報.M002"
            ],
            output="個別DMドラフト#default/M002"
        )
        
        # [Wiring Check] 出力IDが動的に解決されているか
        sim.assert_wiring(
            bob_node_path,
            output="個別DMドラフト#default/M002"
        )

        # --- 5. Action: Complete All Workers ---
        sim.complete_node(path_suffix="M001/worker_0")
        sim.complete_node(path_suffix="M002/worker_0")
        result = sim.complete_node(path_suffix="M003/worker_0")
        sim.dump_analysis_result(result, "03_all_complete")

        # --- 6. Final Verification ---
        # 全工程が完了し、JobがALL_DONE（シミュレータ上は完了）になっていること
        sim.assert_simulation_state(
            running=[],
            completed=["root/serial_0", "iterate_1"] + expected_workers
        )