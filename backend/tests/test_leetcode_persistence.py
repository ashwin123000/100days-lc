import pytest

from backend.app import leetcode_persistence


class FakeSnapshot:
    def __init__(self, value):
        self._value = value
        self.exists = value is not None
        self.id = ""

    def to_dict(self):
        return self._value.copy() if self._value is not None else None

    def get(self, key):
        return self._value.get(key) if self._value is not None else None


class FakeReference:
    def __init__(self, database, collection_name, document_id):
        self.database = database
        self.collection_name = collection_name
        self.document_id = document_id
        self.id = document_id

    def get(self, transaction=None):
        if transaction is not None:
            return transaction.get(self)
        value = self.database.collections.get(self.collection_name, {}).get(self.document_id)
        snapshot = FakeSnapshot(value)
        snapshot.id = self.document_id
        return snapshot


class FakeCollection:
    def __init__(self, database, collection_name):
        self.database = database
        self.collection_name = collection_name

    def document(self, document_id):
        return FakeReference(self.database, self.collection_name, document_id)


class FakeTransaction:
    def __init__(self, database):
        self.database = database
        self.writes = []

    def get(self, reference):
        return reference.get()

    def set(self, reference, value):
        self.writes.append(("set", reference, value))

    def update(self, reference, value):
        self.writes.append(("update", reference, value))

    def delete(self, reference):
        self.writes.append(("delete", reference, None))

    def commit(self):
        for operation, reference, value in self.writes:
            collection = self.database.collections.setdefault(reference.collection_name, {})
            if operation == "set":
                collection[reference.document_id] = value.copy()
            elif operation == "delete":
                collection.pop(reference.document_id, None)
            else:
                document = collection[reference.document_id]
                for key, item in value.items():
                    if item is leetcode_persistence.firestore.DELETE_FIELD:
                        document.pop(key, None)
                    else:
                        document[key] = item


class FakeDatabase:
    def __init__(self):
        self.collections = {
            "users": {
                "learner-1": {
                    "uid": "learner-1",
                    "role": "learner",
                    "isActive": True,
                    "fullName": "Learner One",
                    "bookmarks": ["preserved"],
                },
                "learner-2": {
                    "uid": "learner-2",
                    "role": "learner",
                    "isActive": True,
                },
            },
            "leetcodeUsernameClaims": {},
        }

    def collection(self, collection_name):
        return FakeCollection(self, collection_name)

    def transaction(self):
        return FakeTransaction(self)


@pytest.fixture
def fake_firestore(monkeypatch):
    database = FakeDatabase()
    monkeypatch.setattr(leetcode_persistence, "firestore_client", lambda: database)

    def transactional(function):
        def execute(transaction):
            result = function(transaction)
            transaction.commit()
            return result

        return execute

    monkeypatch.setattr(leetcode_persistence.firestore, "transactional", transactional)
    return database


def test_username_claim_is_transactional_and_cannot_be_taken_by_another_learner(fake_firestore):
    leetcode_persistence.connect_leetcode_username("learner-1", "Public_Name")

    assert fake_firestore.collections["users"]["learner-1"]["leetcodeUsername"] == "Public_Name"
    assert fake_firestore.collections["leetcodeUsernameClaims"]["public_name"] == {"uid": "learner-1"}
    with pytest.raises(leetcode_persistence.LeetCodeUsernameAlreadyClaimed):
        leetcode_persistence.connect_leetcode_username("learner-2", "public_name")
    assert "leetcodeUsername" not in fake_firestore.collections["users"]["learner-2"]


def test_disconnect_removes_only_link_and_claim(fake_firestore):
    leetcode_persistence.connect_leetcode_username("learner-1", "public_name")

    assert leetcode_persistence.disconnect_leetcode_username("learner-1") is True
    learner = fake_firestore.collections["users"]["learner-1"]
    assert learner["fullName"] == "Learner One"
    assert learner["bookmarks"] == ["preserved"]
    assert "leetcodeUsername" not in learner
    assert "public_name" not in fake_firestore.collections["leetcodeUsernameClaims"]
    assert leetcode_persistence.disconnect_leetcode_username("learner-1") is False


def test_only_active_learner_profiles_can_be_linked(fake_firestore):
    fake_firestore.collections["users"]["learner-2"]["role"] = "admin"
    with pytest.raises(leetcode_persistence.LearnerProfileNotFound):
        leetcode_persistence.connect_leetcode_username("learner-2", "public_name")
    assert "public_name" not in fake_firestore.collections["leetcodeUsernameClaims"]
