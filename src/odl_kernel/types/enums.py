# Copyright (c) 2026 Centillion System, Inc. All rights reserved.
#
# This software is licensed under the Business Source License 1.1 (BSL 1.1).
# For full license terms, see the LICENSE file in the root directory.
#
# This software is "Source Available" but contains certain restrictions on
# commercial use and managed service provision. 
# Usage by organizations with gross revenue exceeding $10M USD requires 
# a commercial license.

from enum import StrEnum, auto

# odl-lang からの再エクスポート (便利のため)
from odl.types import OpCode, NodeType

class JobStatus(StrEnum):
    """
    ジョブ全体のライフサイクルステータス
    cocrea_runtime-2202: status_definition.job_status
    """
    CREATED = "CREATED"       # 定義済み・未実行
    RUNNING = "RUNNING"       # 自動処理進行中
    STOPPING = "STOPPING"     # 停止処理中（Cancel予約 / 沈静化フェーズ）
    CANCELLED = "CANCELLED"   # 停止確定
    ALL_DONE = "ALL_DONE"     # 自動処理完了・承認待ち
    CLOSED = "CLOSED"         # 完了儀式済み・アーカイブ（Immutable）
    FAILED = "FAILED"         # 異常停止

class LifecycleStatus(StrEnum):
    """
    ノードの「生存状態」
    cocrea_runtime-2202: status_definition.lifecycle_status
    Note: SKIPPEDやWAITINGは存在しない（SKIPPEDなき世界の原則）
    """
    PENDING = "PENDING"     # 次実行すべきもの (Ready)
    RUNNING = "RUNNING"     # 実行中のもの (Active)
    COMPLETED = "COMPLETED" # 完了済みのもの (Immutable)
    FAILED = "FAILED"       # 異常停止


class BusinessResult(StrEnum):
    """
    完了したノードの「成果の質」
    cocrea_runtime-2202: status_definition.business_result
    """
    NONE = "NONE"       # 未完了、または判定不能
    SUCCESS = "SUCCESS" # 承認、成功
    REJECT = "REJECT"   # 否認、差し戻し
    ERROR = "ERROR"     # 業務継続不可能なエラー
