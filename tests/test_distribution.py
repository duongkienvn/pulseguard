import asyncio
import importlib
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DISTRIBUTION_DIR = PROJECT_ROOT / "distribution_service"


def load_distribution_module():
    sys.modules.pop("main", None)
    sys.path.insert(0, str(DISTRIBUTION_DIR))
    try:
        return importlib.import_module("main")
    finally:
        sys.path.remove(str(DISTRIBUTION_DIR))


class FakeWebSocket:
    def __init__(self, fail_send=False):
        self.fail_send = fail_send
        self.sent = []

    async def accept(self):
        return None

    async def send_text(self, message):
        if self.fail_send:
            raise RuntimeError("closed")
        self.sent.append(message)


def test_connection_manager_removes_dead_socket_on_send_failure():
    main = load_distribution_module()
    manager = main.ConnectionManager()
    dead_socket = FakeWebSocket(fail_send=True)

    async def run():
        await manager.connect(dead_socket, user_id=1, agent_id=10)
        await manager.send_to_user(user_id=1, message='{"ok": true}', agent_id=10)

    asyncio.run(run())

    assert dead_socket not in manager.connection_info
    assert manager.user_connections == {}


def test_connection_manager_preserves_filtered_live_connections():
    main = load_distribution_module()
    manager = main.ConnectionManager()
    matching = FakeWebSocket()
    other_agent = FakeWebSocket()

    async def run():
        await manager.connect(matching, user_id=1, agent_id=10)
        await manager.connect(other_agent, user_id=1, agent_id=11)
        await manager.send_to_user(user_id=1, message='{"agent_id": 10}', agent_id=10)

    asyncio.run(run())

    assert matching.sent == ['{"agent_id": 10}']
    assert other_agent.sent == []
    assert len(manager.user_connections[1]) == 2
