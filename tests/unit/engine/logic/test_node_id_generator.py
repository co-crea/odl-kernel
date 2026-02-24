import uuid
from uuid import UUID
import pytest
from odl_kernel.engine.logic.node_id_generator import NodeIdGenerator

class TestNodeIdGenerator:
    
    # =========================================================================
    # TC-CORE-ID-001: Deterministic Generation
    # =========================================================================
    def test_deterministic_generation(self):
        """[TC-CORE-ID-001] 同じJob ID(str)とPathからは、常に同じUUIDが生成されること"""
        # Job ID は文字列
        job_id_str = "job1-proj1-dom1"
        gen = NodeIdGenerator(job_id=job_id_str)
        path = "root/serial_0/loop_0/v1/worker_0"

        # 1回目の生成
        id_1 = gen.generate(path)
        parsed_uuid = uuid.UUID(id_1)
        assert parsed_uuid.version == 5  # UUID v5であることを確認

        # 2回目の生成 (同じ入力)
        id_2 = gen.generate(path)
        
        # 完全に一致すること
        assert id_1 == id_2

        # 異なるパスなら異なるIDになること
        id_other = gen.generate("root/serial_0/loop_0/v2/worker_0")
        assert id_1 != id_other

        # 異なるJob ID文字列なら、同じパスでも異なるIDになること
        other_gen = NodeIdGenerator(job_id="job2-proj1-dom1")
        id_other_job = other_gen.generate(path)
        assert id_1 != id_other_job

    # =========================================================================
    # TC-CORE-ID-002: Hierarchy Consistency
    # =========================================================================
    def test_hierarchy_consistency(self):
        """[TC-CORE-ID-002] パス文字列の微妙な違い（区切り文字等）が区別されること"""
        job_id = "test-job-id"
        gen = NodeIdGenerator(job_id=job_id)

        # 通常のパス
        id_normal = gen.generate("parent/child")
        
        # スラッシュが多いパス (別物として扱われるべき)
        id_double_slash = gen.generate("parent//child")
        
        assert id_normal != id_double_slash

    def test_empty_job_id_error(self):
        """Job IDが空文字の場合はエラーにすること"""
        with pytest.raises(ValueError):
            NodeIdGenerator(job_id="")