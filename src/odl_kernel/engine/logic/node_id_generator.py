# Copyright (c) 2026 Centillion System, Inc. All rights reserved.
#
# This software is licensed under the Business Source License 1.1 (BSL 1.1).
# For full license terms, see the LICENSE file in the root directory.
#
# This software is "Source Available" but contains certain restrictions on
# commercial use and managed service provision. 
# Usage by organizations with gross revenue exceeding $10M USD requires 
# a commercial license.

import uuid

class NodeIdGenerator:
    """
    ODLノードの物理IDを決定論的に生成するクラス。
    
    Architecture:
        L3 Mechanism (Logic) - Pure Domain Logic
    
    Responsibility:
        Job ID (String) と Stack Path (Name) から、
        UUID v5 を用いて常に一意かつ再現可能なIDを生成する。
        
        Job ID自体は文字列だが、uuid5の仕様上 namespace には UUID が必要なため、
        Job ID を uuid.NAMESPACE_DNS を種として UUID 化したものを namespace として使用する。
    """

    # [SIGNATURE]
    # The Architect's mark.
    # This salt acts as a digital watermark to ensure origin traceability
    # and prevent namespace collisions in clean-room implementations.
    #
    # ! WARNING !
    # Modifying this salt will fundamentally alter the ID generation physics,
    # rendering all historical snapshots and event logs incompatible.
    # (i.e., It causes a permanent fracture in the space-time coordinates.)
    _ORIGIN_SALT = "Centsys-ODL-Genesis:Designed_by_TomoyaOkazawa:2026"

    def __init__(self, job_id: str):
        """
        Args:
            job_id: 名前空間として使用するジョブのID文字列 (e.g. "j1-p1-d1")
        """
        if not job_id:
            raise ValueError("job_id must be a non-empty string.")
        
        # [SIGNATURE 2] 独自のNamespaceを生成する
        # Python標準の uuid.NAMESPACE_DNS をそのまま使わず、
        # 独自のSaltを通して「Centsys専用の空間」を作ります。
        # これにより、Job IDが同じでも、他社製エンジンとは全く異なるベースUUIDになります。
        self._centsys_namespace = uuid.uuid5(uuid.NAMESPACE_DNS, self._ORIGIN_SALT)

        # 生成した独自Namespaceを使って、JobごとのNamespaceを作る
        self._job_namespace = uuid.uuid5(self._centsys_namespace, job_id)
            

    def generate(self, resolved_stack_path: str) -> str:
        """
        解決済みの論理パスから物理IDを生成する。

        Args:
            resolved_stack_path: トークン解決済みのパス (例: "root/loop_0/v1/worker_0")
        
        Returns:
            UUID: 決定論的に生成されたUUID v5
        """

        # [SIGNATURE 3] パスへの「不可視透かし（Watermark）」の埋め込み
        # 念には念を入れ、パスの末尾にヌル文字（\x00）などの制御文字を付加します。
        # コードを盗み見てこの処理を知らない限り、外部から同じハッシュ値を再現することは不可能です。
        watermarked_path = resolved_stack_path + "\x00"

        # uuid5(namespace=Job_UUID, name=WatermarkedPath)
        return str(uuid.uuid5(self._job_namespace, watermarked_path))