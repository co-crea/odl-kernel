# Copyright (c) 2026 Centillion System, Inc. All rights reserved.
#
# This software is licensed under the Business Source License 1.1 (BSL 1.1).
# For full license terms, see the LICENSE file in the root directory.
#
# This software is "Source Available" but contains certain restrictions on
# commercial use and managed service provision. 
# Usage by organizations with gross revenue exceeding $10M USD requires 
# a commercial license.

from __future__ import annotations
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, ConfigDict, Field

# ODL Standard Types (L1 Physics)
# odl-lang ライブラリから標準型を借用する
from odl.types import IrComponent, OpCode, NodeType, WiringObject

# Kernel Enums (L0 Vocabulary)
from .enums import LifecycleStatus, BusinessResult, JobStatus

class ContextSchema(BaseModel):
    """
    実行時に変動・蓄積されるコンテキスト情報 (Memory)
    ユーザー変数とシステム変数を明確に分離して管理する。
    """
    user_variables: Dict[str, Any] = Field(
        default_factory=dict, 
        description="ユーザー定義変数 (継承・上書き可能)"
    )
    system_variables: Dict[str, Any] = Field(
        default_factory=dict, 
        description="カーネル制御変数 ($LOOP, $KEY, $PREV等)"
    )
    children_ids: List[str] = Field(
        default_factory=list, 
        description="生成済み子ノードの物理IDリスト"
    )
    output_aggregation: List[Any] = Field(
        default_factory=list, 
        description="子孫ノードから集約された成果物リスト"
    )

class ProcessNode(BaseModel):
    """
    ODL実行における「プロセスノード」の純粋実体。
    
    [Input/Output共通モデル]
    Snapshot(Input)の一部としてKernelに入力され、
    計算によって更新された状態がAnalysisResult(Output)として返される。
    
    Design Policy:
        - DBモデル(BaseDatabaseModel)を継承しない。
        - 純粋な Pydantic Model として定義する。
        - これにより、計算ロジック(L3)のテストにおいてDBモックが不要となる。
    """

    # Pydantic V2 Config: DBモデルではないので、定義外の不正なフィールド混入を禁止する
    model_config = ConfigDict(extra="ignore")

    # --- Identity ---
    node_id: str = Field(..., description="ノードを一意に特定する物理アドレス")
    stack_path: str = Field(..., description="トークン解決済みの物理パス文字列")

    # --- Type & Definition (Immutable) ---
    # 生成後に変化しない静的な定義情報
    node_type: NodeType = Field(..., description="ノードの振る舞い分類 (ACTION/CONTROL/LOGIC)")
    opcode: OpCode = Field(..., description="具体的な命令種別")
    
    children_blueprint: List[IrComponent] = Field(
        default_factory=list, 
        description="子ノード定義リスト (Control Nodeのみ保持)"
    )
    wiring: WiringObject = Field(..., description="入出力定義 (解決済みのパスを持つ)")
    params: Dict[str, Any] = Field(default_factory=dict, description="静的パラメータ")

    # --- State (Mutable) ---
    # 実行に伴って変化する動的な状態情報
    lifecycle_status: LifecycleStatus = Field(default=LifecycleStatus.PENDING)
    business_result: BusinessResult = Field(default=BusinessResult.NONE)
    
    runtime_context: ContextSchema = Field(default_factory=ContextSchema)
    
    # --- Time Constraints ---
    timeout_at: Optional[float] = Field(None, description="タイムアウト時刻 (Unix Timestamp)")


class Job(BaseModel):
    """
    ODL実行の親コンテナとなる「ジョブ」の純粋実体。
    Kernelはジョブ全体のステータス制御や、グローバルコンテキストの参照に使用する。
    """

    # Pydantic V2 Config: Jobは管理情報を持つ可能性があるが、Kernelは関知しないフィールドを無視する
    model_config = ConfigDict(extra="ignore")

    job_id: str = Field(..., description="ジョブID (e.g. j1-p1-d1)")
    status: JobStatus = Field(..., description="ジョブのライフサイクル状態")
    
    ir_root: IrComponent = Field(..., description="ジョブ全体のマスター定義（ASTオブジェクト）")
    
    root_node_id: Optional[str] = Field(None, description="ルートノードのID")
    global_context: Dict[str, Any] = Field(default_factory=dict, description="ジョブ初期入力データ")
