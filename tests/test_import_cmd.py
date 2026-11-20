import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from hobees.cli.import_cmd import import_config
from hobees.db.models import Base, Bee, Hive, HiveMembership, LLMProvider
from hobees.db.session import session_scope


def test_config_import_reconciles_existing_resources(tmp_path, monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr("hobees.db.session.get_session_factory", lambda: factory)

    config_path = tmp_path / "config.json"
    config = {
        "providers": [
            {
                "alias": "sync-provider",
                "provider_type": "openai",
                "api_key_env": "NONE",
                "default_model": "model-v1",
            }
        ],
        "bees": [
            {
                "name": "sync-worker-a",
                "provider": "sync-provider",
                "role_description": "worker A v1",
                "model": "model-v1",
            },
            {
                "name": "sync-worker-b",
                "provider": "sync-provider",
                "role_description": "worker B",
                "model": "model-v1",
            },
        ],
        "hives": [
            {
                "name": "sync-hive",
                "supervisor_provider": "sync-provider",
                "supervisor_model": "model-v1",
                "bees": ["sync-worker-a"],
            }
        ],
    }

    def apply_config():
        config_path.write_text(json.dumps(config), encoding="utf-8")
        import_config(config_path, force=True)

    apply_config()
    config["providers"][0]["default_model"] = "model-v2"
    config["bees"][0]["role_description"] = "worker A v2"
    config["hives"][0]["supervisor_model"] = "model-v2"
    config["hives"][0]["bees"] = ["sync-worker-b"]
    apply_config()

    with session_scope() as session:
        provider = session.query(LLMProvider).filter_by(alias="sync-provider").one()
        bee = session.query(Bee).filter_by(name="sync-worker-a").one()
        hive = session.query(Hive).filter_by(name="sync-hive").one()
        member_names = {
            membership.bee.name
            for membership in session.query(HiveMembership).filter_by(hive_id=hive.id)
        }

        assert session.query(LLMProvider).filter_by(alias="sync-provider").count() == 1
        assert session.query(Bee).filter_by(name="sync-worker-a").count() == 1
        assert provider.default_model == "model-v2"
        assert bee.role_description == "worker A v2"
        assert hive.supervisor_model_name == "model-v2"
        assert member_names == {"sync-worker-b"}

    engine.dispose()
