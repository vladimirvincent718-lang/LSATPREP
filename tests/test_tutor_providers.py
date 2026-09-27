import json
import urllib.error
import pytest
from src import tutor_providers as providers


class Response:
    def __init__(self,data):self.data=data
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,limit):return json.dumps(self.data).encode()


def job(provider='gemini'):
    return dict(user_id=1,provider=provider,model='test-model',kind='reply',context={'conversation':[{'text':'Help'}]})


@pytest.mark.parametrize('provider',['gemini','openai'])
def test_requests_use_fixed_endpoints_bounded_output_and_private_headers(monkeypatch,provider):
    monkeypatch.setattr(providers,'read_key',lambda *args:'test-placeholder-key')
    def request(req,timeout):
        body=json.loads(req.data)
        assert timeout==90
        assert 'test-placeholder-key' not in req.full_url and 'test-placeholder-key' not in req.data.decode()
        assert 'untrusted study data' in (body['systemInstruction']['parts'][0]['text'] if provider=='gemini' else body['instructions'])
        text=json.dumps({'needs_followup':True,'reply':'An answer.'})
        if provider=='gemini':
            assert req.full_url=='https://generativelanguage.googleapis.com/v1beta/models/test-model:generateContent'
            assert req.get_header('X-goog-api-key')=='test-placeholder-key'
            assert body['generationConfig']['maxOutputTokens']==2048
            return Response({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'private thoughts','thought':True},{'text':text}]}}]})
        assert req.full_url=='https://api.openai.com/v1/responses'
        assert body['store'] is False and body['max_output_tokens']==1200
        return Response({'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':text}]}]})
    monkeypatch.setattr(providers.urllib.request,'urlopen',request)
    assert providers.generate(job(provider))['reply']=='An answer.'


@pytest.mark.parametrize('data',[
    {'candidates':[]},
    {'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'{}'}]}}]},
    {'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"needs_followup":"false","reply":"x"}'}]}}]},
    {'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"needs_followup":true,"reply":""}'}]}}]},
])
def test_invalid_or_incomplete_provider_answers_are_not_published(monkeypatch,data):
    monkeypatch.setattr(providers,'read_key',lambda *args:'test-placeholder-key')
    monkeypatch.setattr(providers.urllib.request,'urlopen',lambda *args,**kwargs:Response(data))
    with pytest.raises(providers.TutorError,match='incomplete or unreadable'):providers.generate(job())


def test_api_failure_never_exposes_response_body_or_key_or_retries(monkeypatch):
    monkeypatch.setattr(providers,'read_key',lambda *args:'test-placeholder-key')
    calls=[]
    def failed(req,timeout):
        calls.append(True)
        raise urllib.error.HTTPError(req.full_url,429,'sensitive provider details',None,None)
    monkeypatch.setattr(providers.urllib.request,'urlopen',failed)
    with pytest.raises(providers.TutorError,match='No automatic retry') as exc:providers.generate(job())
    assert len(calls)==1 and 'sensitive' not in str(exc.value)
