from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey,
    Integer, String, Text, Enum as SAEnum,
)
from sqlalchemy.orm import DeclarativeBase, relationship
import enum


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    phone = Column(String(20), nullable=True)
    full_name = Column(String(100), nullable=True)
    username = Column(String(50), nullable=True)
    trial_expires_at = Column(DateTime, nullable=True)
    is_premium = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    accounts = relationship("TelegramAccount", back_populates="user", cascade="all, delete-orphan")
    announcements = relationship("Announcement", back_populates="user")


class TelegramAccount(Base):
    __tablename__ = "telegram_accounts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    phone = Column(String(20), nullable=False)
    session_string = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="accounts")
    groups = relationship("Group", back_populates="account", cascade="all, delete-orphan")
    announcements = relationship("Announcement", back_populates="account")


class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("telegram_accounts.id"), nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    title = Column(String(200), nullable=False)
    username = Column(String(100), nullable=True)
    member_count = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("TelegramAccount", back_populates="groups")


class MessageType(enum.Enum):
    text = "text"
    photo = "photo"


class AnnouncementStatus(enum.Enum):
    scheduled = "scheduled"
    stopped = "stopped"


class Announcement(Base):
    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("telegram_accounts.id"), nullable=True)
    message_type = Column(SAEnum(MessageType), nullable=False, default=MessageType.text)
    text = Column(Text, nullable=False)
    photo_file_id = Column(String(200), nullable=True)
    interval_minutes = Column(Integer, nullable=False, default=30)
    is_active = Column(Boolean, default=True)
    next_send_at = Column(DateTime, nullable=True)
    last_sent_at = Column(DateTime, nullable=True)
    status = Column(SAEnum(AnnouncementStatus), default=AnnouncementStatus.scheduled)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="announcements")
    account = relationship("TelegramAccount", back_populates="announcements")
    group_links = relationship("AnnouncementGroup", back_populates="announcement", cascade="all, delete-orphan")
    send_log = relationship("AnnouncementSend", back_populates="announcement", cascade="all, delete-orphan")


class AnnouncementGroup(Base):
    __tablename__ = "announcement_groups"

    id = Column(Integer, primary_key=True)
    announcement_id = Column(Integer, ForeignKey("announcements.id"), nullable=False)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)

    announcement = relationship("Announcement", back_populates="group_links")
    group = relationship("Group")


class PaymentRequest(Base):
    """Tracks every subscription payment receipt submitted by users."""
    __tablename__ = "payment_requests"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tariff_key = Column(String(20), nullable=True)   # e.g. "1_oy"
    tariff_name = Column(String(50), nullable=True)
    amount = Column(Integer, default=0)              # in UZS
    receipt_file_id = Column(String(200), nullable=True)  # Telegram photo file_id
    status = Column(String(20), default="pending")   # pending / approved / rejected
    admin_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    user = relationship("User")


class AnnouncementSend(Base):
    __tablename__ = "announcement_sends"

    id = Column(Integer, primary_key=True)
    announcement_id = Column(Integer, ForeignKey("announcements.id"), nullable=False)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    message_id = Column(BigInteger, nullable=True)
    status = Column(String(20), default="pending")
    error = Column(Text, nullable=True)
    sent_at = Column(DateTime, nullable=True)

    announcement = relationship("Announcement", back_populates="send_log")
