# 匯入所有 model，讓 Base.metadata 完整（Alembic autogenerate 與 create_all 依賴這點）
from app.models.metric import Metric
from app.models.record import Record
from app.models.system_log import SystemLog
from app.models.user import Role, User

__all__ = ["Metric", "Record", "Role", "SystemLog", "User"]
