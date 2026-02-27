"""
Pydantic schemas for Splintarr API.

This module exports all request and response schemas for easy imports.
"""

from .instance import (
    InstanceCreate,
    InstanceResponse,
    InstanceTestResult,
    InstanceType,
    InstanceUpdate,
)
from .search import (
    SearchExecutionStatus,
    SearchHistoryResponse,
    SearchQueueCreate,
    SearchQueueResponse,
    SearchQueueStatus,
    SearchQueueUpdate,
    SearchStrategy,
)
from .user import (
    LoginSuccess,
    MessageResponse,
    PasswordChange,
    TokenResponse,
    TwoFactorDisable,
    TwoFactorSetup,
    TwoFactorVerify,
    UserLogin,
    UserRegister,
    UserResponse,
)

__all__ = [
    # User schemas
    "UserRegister",
    "UserLogin",
    "UserResponse",
    "TokenResponse",
    "TwoFactorSetup",
    "TwoFactorVerify",
    "TwoFactorDisable",
    "MessageResponse",
    "LoginSuccess",
    "PasswordChange",
    # Instance schemas
    "InstanceCreate",
    "InstanceUpdate",
    "InstanceResponse",
    "InstanceTestResult",
    "InstanceType",
    # Search schemas
    "SearchQueueCreate",
    "SearchQueueUpdate",
    "SearchQueueResponse",
    "SearchHistoryResponse",
    "SearchStrategy",
    "SearchQueueStatus",
    "SearchExecutionStatus",
]
