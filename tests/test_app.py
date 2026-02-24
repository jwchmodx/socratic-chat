"""Python unit tests for socratic-chat app"""
import os
import sys
import json
import pytest
import shutil

# TEST_MODE 강제 설정
os.environ['TEST_MODE'] = 'true'
os.environ['PORT'] = '8001'

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, tokenize, compute_tfidf, cosine_similarity, detect_previous_reference


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def cleanup():
    """테스트 후 데이터 정리"""
    yield
    conv_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "conversations")
    for prefix in ['pytest_user', '_anonymous']:
        path = os.path.join(conv_dir, prefix)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)


class TestTokenizer:
    def test_korean(self):
        tokens = tokenize("카페 창업을 준비하고 있어")
        assert "카페" in tokens
        # 토크나이저가 '창업을'로 잡을 수 있음 (조사 포함)
        assert any("창업" in t for t in tokens)

    def test_english(self):
        tokens = tokenize("hello world test")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens

    def test_stopwords_removed(self):
        tokens = tokenize("이것은 테스트입니다")
        assert "은" not in tokens

    def test_empty(self):
        assert tokenize("") == []


class TestTFIDF:
    def test_basic(self):
        docs = ["카페 창업", "레스토랑 창업", "카페 디자인"]
        vectors = compute_tfidf(docs)
        assert len(vectors) == 3

    def test_similarity(self):
        docs = ["카페 창업 준비", "카페 메뉴 개발", "전혀 다른 내용"]
        vectors = compute_tfidf(docs)
        sim_01 = cosine_similarity(vectors[0], vectors[1])
        sim_02 = cosine_similarity(vectors[0], vectors[2])
        # 카페 관련 문서끼리 유사도가 더 높아야
        assert sim_01 > sim_02


class TestPreviousReference:
    def test_detects_korean(self):
        assert detect_previous_reference("이전에 했던 거 기억나?")
        assert detect_previous_reference("지난번 프로젝트에서")
        assert detect_previous_reference("저번에 이야기했던")
        assert detect_previous_reference("예전에 만든 거")

    def test_no_false_positive(self):
        assert not detect_previous_reference("카페 창업 준비")
        assert not detect_previous_reference("새로운 아이디어")


class TestAPI:
    def test_index(self, client):
        resp = client.get('/')
        assert resp.status_code == 200

    def test_set_user(self, client):
        resp = client.post('/set_user', json={'nickname': 'pytest_user'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['user'] == 'pytest_user'

    def test_set_user_empty(self, client):
        resp = client.post('/set_user', json={'nickname': ''})
        assert resp.status_code == 400

    def test_chat_test_mode(self, client):
        client.post('/set_user', json={'nickname': 'pytest_user'})
        client.post('/create_project', json={'name': 'test'})
        resp = client.post('/chat', json={'message': '안녕하세요'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert '테스트 응답' in data['response']

    def test_chat_empty(self, client):
        resp = client.post('/chat', json={'message': ''})
        assert resp.status_code == 400

    def test_search_empty(self, client):
        resp = client.post('/search', json={'query': ''})
        assert resp.status_code == 400

    def test_search(self, client):
        client.post('/set_user', json={'nickname': 'pytest_user'})
        client.post('/create_project', json={'name': 'search_test'})
        client.post('/chat', json={'message': '인공지능 스타트업'})
        resp = client.post('/search', json={'query': '인공지능', 'mode': 'tfidf'})
        assert resp.status_code == 200

    def test_search_modes(self, client):
        client.post('/set_user', json={'nickname': 'pytest_user'})
        for mode in ['tfidf', 'vector', 'hybrid']:
            resp = client.post('/search', json={'query': 'test', 'mode': mode})
            assert resp.status_code == 200
            assert resp.get_json()['mode'] == mode

    def test_projects_crud(self, client):
        client.post('/set_user', json={'nickname': 'pytest_user'})
        
        # Create
        resp = client.post('/create_project', json={'name': 'proj1'})
        assert resp.status_code == 200
        
        # List
        resp = client.get('/projects')
        projects = resp.get_json()
        assert any(p['name'] == 'proj1' for p in projects)
        
        # Delete
        resp = client.delete('/delete_project/proj1')
        assert resp.status_code == 200

    def test_reset(self, client):
        resp = client.post('/reset')
        assert resp.status_code == 200

    def test_memory(self, client):
        client.post('/set_user', json={'nickname': 'pytest_user'})
        client.post('/create_project', json={'name': 'mem_test'})
        resp = client.get('/memory')
        assert resp.status_code == 200

    def test_report(self, client):
        client.post('/set_user', json={'nickname': 'pytest_user'})
        client.post('/create_project', json={'name': 'report_test'})
        client.post('/chat', json={'message': '테스트 내용'})
        resp = client.post('/report', json={'force': True})
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'report' in data

    def test_previous_reference_in_chat(self, client):
        client.post('/set_user', json={'nickname': 'pytest_user'})
        client.post('/create_project', json={'name': 'ref_test'})
        resp = client.post('/chat', json={'message': '이전에 했던 거 기억나?'})
        assert resp.status_code == 200

    def test_logout(self, client):
        resp = client.get('/logout')
        assert resp.status_code in (200, 302)
