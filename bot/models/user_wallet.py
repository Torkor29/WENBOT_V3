"""UserWallet model — supports multiple wallets per user."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow


class UserWallet(Base):
    __tablename__ = "user_wallets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # For l'instant, on utilise surtout Polygon, mais on laisse un champ
    # générique pour éventuellement ajouter Solana ou d'autres chains.
    chain: Mapped[str] = mapped_column(String(32), default="polygon", nullable=False)

    address: Mapped[str] = mapped_column(String(255), nullable=False)

    # Indique si ce wallet a été créé par le bot (vs importé).
    auto_created: Mapped[bool] = mapped_column(Boolean, default=False)

    # Indique le wallet actuellement utilisé pour le copy-trading.
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    # On laisse la possibilité de stocker une clé chiffrée par wallet
    # si on veut aller plus loin plus tard. Aujourd'hui on continue à
    # utiliser les champs existants sur User pour compatibilité.
    encrypted_key: Mapped[Optional[bytes]] = mapped_column(nullable=True)

    label: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    user: Mapped["User"] = relationship("User", back_populates="wallets")

    def __repr__(self) -> str:
        return f"<UserWallet user_id={self.user_id} chain={self.chain} primary={self.is_primary}>"


from .user import User  # noqa: E402,F401

