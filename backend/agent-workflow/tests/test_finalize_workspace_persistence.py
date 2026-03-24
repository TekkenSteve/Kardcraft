from kardcraft.workflow.graphs.main_graph import utils as graph_utils


class _FakeCreatedCard:
    def __init__(self, card_id: str):
        self.card_id = card_id


class _FakeCardRepository:
    def __init__(self, session):
        self.session = session
        self.calls = []

    async def create_card(self, owner, model, content_data, concepts, comment):
        card_id = f"card-{len(self.calls) + 1}"
        self.calls.append(
            {
                "owner": owner,
                "model": model,
                "content_data": content_data,
                "concepts": concepts,
                "comment": comment,
                "card_id": card_id,
            }
        )
        return _FakeCreatedCard(card_id)


class _FakeSessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePostgres:
    def __init__(self):
        self._initialized = False
        self.initialize_calls = 0

    async def initialize(self):
        self._initialized = True
        self.initialize_calls += 1

    def session(self):
        return _FakeSessionContext()


class _FakePackWorkspace:
    def __init__(self):
        self.created = []
        self.added = []

    async def get_workspace(self, session_id):
        return None

    async def create_workspace(self, session_id):
        self.created.append(session_id)
        return {"session_id": session_id}

    async def add_cards(self, session_id, cards, source):
        self.added.append((session_id, cards, source))
        return True


async def test_save_cards_to_workspace_uses_workspace_id_and_persists(monkeypatch):
    fake_pg = _FakePostgres()
    fake_pack = _FakePackWorkspace()
    fake_repo = _FakeCardRepository(session=object())

    monkeypatch.setattr(graph_utils, "postgres", fake_pg)
    monkeypatch.setattr(graph_utils, "pack_workspace", fake_pack)
    monkeypatch.setattr(graph_utils, "CardRepository", lambda session: fake_repo)

    cards = [
        {"front": "Q1", "back": "A1", "model": "basic", "id": "tmp-1"},
        {"front": "Q2", "back": "A2", "model": "basic", "id": "tmp-2"},
    ]
    saved = await graph_utils.save_cards_to_workspace(
        cards=cards,
        workspace_id="ws-abc",
        owner="u-1",
    )

    assert fake_pg.initialize_calls == 1
    assert len(fake_repo.calls) == 2
    assert saved == ["card-1", "card-2"]
    assert fake_pack.created == ["ws-abc"]
    assert len(fake_pack.added) == 1
    assert fake_pack.added[0][0] == "ws-abc"
    assert fake_pack.added[0][2] == "ai"


async def test_save_cards_to_workspace_returns_empty_without_workspace_id():
    saved = await graph_utils.save_cards_to_workspace(
        cards=[{"front": "Q1", "back": "A1"}],
        workspace_id="",
        owner="u-1",
    )
    assert saved == []
