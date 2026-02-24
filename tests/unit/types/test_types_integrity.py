import pytest
from uuid import uuid4, UUID
from datetime import datetime
from pydantic import ValidationError

# L1 Types
from odl.types import OpCode, NodeType, WiringObject

# L0 Kernel Types
from odl_kernel.types import (
    ProcessNode, 
    Job, 
    JobSnapshot, 
    LifecycleStatus,
    ContextSchema,
    KernelEvent,
    KernelEventType
)

class TestTypesIntegrity:
    """
    [Guardrail Test]
    odl-kernel の型定義が「純粋性（Purity）」を保っているか検証する。
    DBモデルの混入や、不正なフィールド追加を禁止するルールが機能しているかを確認する。
    """

    def test_process_node_purity_with_ignore_policy(self):
        """
        ProcessNode は計算専用の純粋モデルである。
        定義されていないフィールド（DBのメタデータ等）が入力された場合、
        システムを停止（エラー）させるのではなく、
        「ポステルの法則」に基づき、それらを静かに無視（破棄）して正常にインスタンス化されなければならない。
        """
        node_id = uuid4().hex
        
        # 1. 正常系: 必須フィールドのみで構築可能
        node = ProcessNode(
            node_id=node_id,
            stack_path="root/test",
            node_type=NodeType.ACTION,
            opcode=OpCode.WORKER,
            wiring=WiringObject(inputs=[], output="test"),
            lifecycle_status=LifecycleStatus.PENDING
        )
        assert node.node_id == node_id
        assert node.params == {} # default_factory が機能していること

        # 2. 準正常系: 余計なフィールド（DB都合など）が混入した場合
        # model_config = ConfigDict(extra="ignore") の動作検証
        
        dirty_node = ProcessNode(
            node_id=uuid4().hex,
            stack_path="root/test_ignore",
            node_type=NodeType.ACTION,
            opcode=OpCode.WORKER,
            wiring=WiringObject(inputs=[], output="test"),
            lifecycle_status=LifecycleStatus.PENDING,
            
            # 【検証対象】 インフラ層の都合（余計なゴミ）
            created_at="2024-01-01", 
            firestore_ref="projects/my-proj/databases/...",
            __private_cache="some_cache"
        )
        
        # 検証A: エラーにならずにインスタンス化されていること
        assert isinstance(dirty_node, ProcessNode)
        
        # 検証B: 必要なデータは保持されていること
        assert dirty_node.stack_path == "root/test_ignore"
        
        # 検証C: 余計なデータはきれいに消えている（Ignoreされている）こと
        dumped = dirty_node.model_dump()
        assert "created_at" not in dumped
        assert "firestore_ref" not in dumped
        assert "__private_cache" not in dumped
        
        # 属性としてもアクセスできないこと
        assert not hasattr(dirty_node, "created_at")

    def test_serialization_symmetry(self):
        """
        全てのカーネルオブジェクトは JSON シリアライズ/デシリアライズ可能であり、
        情報の欠損なく復元できなければならない（API通信の要件）。
        """
        original_node = ProcessNode(
            node_id=uuid4().hex,
            stack_path="root/loop/v1/worker",
            node_type=NodeType.ACTION,
            opcode=OpCode.WORKER,
            wiring=WiringObject(inputs=["prev_id"], output="res"),
            lifecycle_status=LifecycleStatus.RUNNING,
            timeout_at=1700000000.0,
            runtime_context=ContextSchema(
                system_variables={"$LOOP": 1},
                user_variables={"summary": "test"}
            )
        )

        # 1. Dump to JSON
        json_str = original_node.model_dump_json()
        assert isinstance(json_str, str)
        assert "root/loop/v1/worker" in json_str

        # 2. Load from JSON
        restored_node = ProcessNode.model_validate_json(json_str)

        # 3. Verify Identity
        assert restored_node == original_node
        assert restored_node.node_id == original_node.node_id
        assert restored_node.runtime_context.system_variables["$LOOP"] == 1

    def test_snapshot_structure(self):
        """
        JobSnapshot が「世界の全て」を正しく表現できるか検証。
        """
        # Job定義 (Mocking IR is omitted for simplicity in this test)
        # Note: 実際には ir_root に有効な IrComponent が必要だが、Pydantic検証だけならMockで通る場合もある
        # ここでは最低限の構造チェックを行う
        from odl.types import IrComponent
        
        job = Job(
            job_id="j1",
            status="RUNNING",
            ir_root=IrComponent(opcode=OpCode.SERIAL, children=[], stack_path="root") 
        )
        
        node_id = uuid4().hex
        node = ProcessNode(
            node_id=node_id,
            stack_path="root",
            node_type=NodeType.CONTROL,
            opcode=OpCode.SERIAL,
            wiring=WiringObject(inputs=[], output=None),
            lifecycle_status=LifecycleStatus.RUNNING
        )

        snapshot = JobSnapshot(
            job=job,
            nodes={node_id: node}
        )

        # 辞書アクセスとRootアクセサの挙動確認
        assert snapshot.nodes[node_id].opcode == OpCode.SERIAL
        assert snapshot.root_node is None # root_node_id 未設定なので None

        # root_node_id を設定した場合
        snapshot.job.root_node_id = node_id
        assert snapshot.root_node == node

    def test_kernel_event_polymorphism(self):
        """
        KernelEvent がペイロードを柔軟に、かつ型安全に保持できるか。
        """
        now = datetime.now()
        event = KernelEvent(
            type=KernelEventType.ACTION_COMPLETED,
            occurred_at=now,
            target_node_id=uuid4().hex,
            payload={
                "result": "SUCCESS",
                "output_data": {"file_id": "123"}
            }
        )
        
        # JSONシリアライズしてWorkerから送られてくる想定
        dumped = event.model_dump_json()
        loaded = KernelEvent.model_validate_json(dumped)
        
        assert loaded.type == KernelEventType.ACTION_COMPLETED
        assert loaded.payload["result"] == "SUCCESS"
        assert loaded.occurred_at == event.occurred_at