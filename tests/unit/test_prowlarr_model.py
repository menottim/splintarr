"""
Unit tests for ProwlarrConfig model.

Tests cover:
- Creating a ProwlarrConfig with required fields and verifying defaults
- Singleton-per-user constraint (unique user_id) raises IntegrityError
- Relationship back to User model
- Repr output
"""

from sqlalchemy.exc import IntegrityError

import pytest

from splintarr.models.prowlarr import ProwlarrConfig
from splintarr.models.user import User


def _create_user(db_session, username="testuser"):
    """Helper to create a User and return it after commit."""
    user = User(username=username, password_hash="argon2id$hash")
    db_session.add(user)
    db_session.commit()
    return user


class TestCreateProwlarrConfig:
    """ProwlarrConfig creation with required fields and default verification."""

    def test_create_with_required_fields(self, db_session):
        """Create a config with only required fields; defaults fill in correctly."""
        user = _create_user(db_session)

        config = ProwlarrConfig(
            user_id=user.id,
            url="http://prowlarr.local:9696",
            encrypted_api_key="gAAAAABf_encrypted_api_key_data",
        )
        db_session.add(config)
        db_session.commit()

        assert config.id is not None
        assert config.user_id == user.id
        assert config.url == "http://prowlarr.local:9696"
        assert config.encrypted_api_key == "gAAAAABf_encrypted_api_key_data"

    def test_verify_ssl_defaults_true(self, db_session):
        """verify_ssl defaults to True."""
        user = _create_user(db_session)
        config = ProwlarrConfig(
            user_id=user.id,
            url="http://prowlarr.local:9696",
            encrypted_api_key="encrypted",
        )
        db_session.add(config)
        db_session.commit()

        assert config.verify_ssl is True

    def test_sync_interval_minutes_defaults_to_60(self, db_session):
        """sync_interval_minutes defaults to 60."""
        user = _create_user(db_session)
        config = ProwlarrConfig(
            user_id=user.id,
            url="http://prowlarr.local:9696",
            encrypted_api_key="encrypted",
        )
        db_session.add(config)
        db_session.commit()

        assert config.sync_interval_minutes == 60

    def test_is_active_defaults_true(self, db_session):
        """is_active defaults to True."""
        user = _create_user(db_session)
        config = ProwlarrConfig(
            user_id=user.id,
            url="http://prowlarr.local:9696",
            encrypted_api_key="encrypted",
        )
        db_session.add(config)
        db_session.commit()

        assert config.is_active is True

    def test_last_sync_at_defaults_to_none(self, db_session):
        """last_sync_at is nullable and defaults to None."""
        user = _create_user(db_session)
        config = ProwlarrConfig(
            user_id=user.id,
            url="http://prowlarr.local:9696",
            encrypted_api_key="encrypted",
        )
        db_session.add(config)
        db_session.commit()

        assert config.last_sync_at is None

    def test_created_at_populated(self, db_session):
        """created_at is set automatically on creation."""
        user = _create_user(db_session)
        config = ProwlarrConfig(
            user_id=user.id,
            url="http://prowlarr.local:9696",
            encrypted_api_key="encrypted",
        )
        db_session.add(config)
        db_session.commit()

        assert config.created_at is not None

    def test_updated_at_populated(self, db_session):
        """updated_at is set automatically on creation."""
        user = _create_user(db_session)
        config = ProwlarrConfig(
            user_id=user.id,
            url="http://prowlarr.local:9696",
            encrypted_api_key="encrypted",
        )
        db_session.add(config)
        db_session.commit()

        assert config.updated_at is not None


class TestSingletonPerUser:
    """ProwlarrConfig enforces one config per user via unique constraint on user_id."""

    def test_second_config_for_same_user_raises_integrity_error(self, db_session):
        """Creating a second ProwlarrConfig for the same user_id raises IntegrityError."""
        user = _create_user(db_session)

        config1 = ProwlarrConfig(
            user_id=user.id,
            url="http://prowlarr.local:9696",
            encrypted_api_key="encrypted_key_1",
        )
        db_session.add(config1)
        db_session.commit()

        config2 = ProwlarrConfig(
            user_id=user.id,
            url="http://prowlarr2.local:9696",
            encrypted_api_key="encrypted_key_2",
        )
        db_session.add(config2)

        with pytest.raises(IntegrityError):
            db_session.commit()

        db_session.rollback()

    def test_different_users_can_each_have_config(self, db_session):
        """Two different users can each have their own ProwlarrConfig."""
        user1 = _create_user(db_session, username="user1")
        user2 = _create_user(db_session, username="user2")

        config1 = ProwlarrConfig(
            user_id=user1.id,
            url="http://prowlarr1.local:9696",
            encrypted_api_key="encrypted_key_1",
        )
        config2 = ProwlarrConfig(
            user_id=user2.id,
            url="http://prowlarr2.local:9696",
            encrypted_api_key="encrypted_key_2",
        )
        db_session.add_all([config1, config2])
        db_session.commit()

        assert config1.id != config2.id
        assert config1.user_id == user1.id
        assert config2.user_id == user2.id


class TestRelationship:
    """ProwlarrConfig <-> User relationship works bidirectionally."""

    def test_config_has_user_relationship(self, db_session):
        """ProwlarrConfig.user navigates back to the owning User."""
        user = _create_user(db_session)
        config = ProwlarrConfig(
            user_id=user.id,
            url="http://prowlarr.local:9696",
            encrypted_api_key="encrypted",
        )
        db_session.add(config)
        db_session.commit()

        assert config.user is not None
        assert config.user.id == user.id
        assert config.user.username == "testuser"

    def test_user_has_prowlarr_config_relationship(self, db_session):
        """User.prowlarr_config returns the singleton ProwlarrConfig (uselist=False)."""
        user = _create_user(db_session)
        config = ProwlarrConfig(
            user_id=user.id,
            url="http://prowlarr.local:9696",
            encrypted_api_key="encrypted",
        )
        db_session.add(config)
        db_session.commit()

        # Refresh to pick up the relationship
        db_session.refresh(user)

        assert user.prowlarr_config is not None
        assert user.prowlarr_config.id == config.id

    def test_user_prowlarr_config_none_when_not_set(self, db_session):
        """User.prowlarr_config is None when no config exists."""
        user = _create_user(db_session)
        db_session.refresh(user)

        assert user.prowlarr_config is None

    def test_cascade_delete_removes_config(self, db_session):
        """Deleting a User cascades to delete their ProwlarrConfig."""
        user = _create_user(db_session)
        config = ProwlarrConfig(
            user_id=user.id,
            url="http://prowlarr.local:9696",
            encrypted_api_key="encrypted",
        )
        db_session.add(config)
        db_session.commit()

        config_id = config.id

        db_session.delete(user)
        db_session.commit()

        result = db_session.query(ProwlarrConfig).filter_by(id=config_id).first()
        assert result is None


class TestRepr:
    """ProwlarrConfig repr output."""

    def test_repr_format(self, db_session):
        """__repr__ includes id, user_id, and is_active."""
        user = _create_user(db_session)
        config = ProwlarrConfig(
            user_id=user.id,
            url="http://prowlarr.local:9696",
            encrypted_api_key="encrypted",
        )
        db_session.add(config)
        db_session.commit()

        repr_str = repr(config)
        assert "ProwlarrConfig" in repr_str
        assert f"user_id={user.id}" in repr_str
        assert "is_active=True" in repr_str
