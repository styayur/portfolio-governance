import json
from scripts.ai_review_adapter import run, _prompt


def fixture():
    context = dict(repository='styayur/example', repositoryId=1, prNumber=1,
                   headSha='a'*40, baseSha='b'*40, body='review changes', title='test',
                   files=[dict(filename=f'src/file{i}.py', patch='+'+str(i)*1500) for i in range(3)])
    risk = dict(headSha='a'*40, baseSha='b'*40, diffSha256='c'*64)
    static = dict(headSha='a'*40, baseSha='b'*40, diffSha256='c'*64)
    config = dict(enabled=True, endpoint='https://example.invalid/v1/chat/completions',
                  model='fixture', apiKey='synthetic', maxChars=4500)
    return context, risk, static, config


def reply(risk, decision='APPROVE'):
    body = dict(headSha=risk['headSha'], baseSha=risk['baseSha'], diffSha256=risk['diffSha256'],
                decision=decision, findings=[], summary='fixture result')
    return dict(choices=[dict(message=dict(content=json.dumps(body)))], usage=dict(prompt_tokens=10, completion_tokens=2))


def test_all_complete_files_are_reviewed_and_usage_is_aggregated():
    context, risk, static, config = fixture()
    seen = []
    def transport(config, prompt):
        data=json.loads(prompt.split('UNTRUSTED_REVIEW_INPUT=',1)[1])
        seen.extend(data['files'])
        assert data['reviewScope']['mode']=='FILE_BATCH'
        assert data['diffSha256']==risk['diffSha256']
        return reply(risk)
    result = run(context, risk, static, config, transport)
    assert result['decision']=='APPROVE'
    assert seen==context['files']
    assert result['usage']['prompt_tokens']==result['completedBatches']*10
    assert result['completedBatches']==result['batchCount']


def test_failed_last_batch_cannot_approve_first_batch():
    context, risk, static, config = fixture()
    calls=[]
    def transport(config, prompt):
        calls.append(prompt)
        if len(calls)>1:
            raise TimeoutError('fixture timeout')
        return reply(risk)
    result=run(context,risk,static,config,transport)
    assert result['status']=='NOT_VERIFIED'
    assert result['decision']=='NOT_VERIFIED'


def test_oversize_single_file_is_never_truncated_or_sent():
    context, risk, static, config = fixture()
    context['files'][0]['patch']='+'+'x'*10000
    calls=[]
    result=run(context,risk,static,config,lambda *args: calls.append(args))
    assert result['decision']=='NOT_VERIFIED'
    assert result['reason']=='AI_REVIEW_SINGLE_FILE_TOO_LARGE'
    assert not calls


def test_scoped_unicode_prompts_stay_inside_the_actual_utf8_byte_budget():
    context, risk, static, config = fixture()
    context['files'] = [dict(filename=f'src/file{i}.py', patch='+' + '界' * 450) for i in range(3)]
    config['maxChars'] = 4500
    seen = []
    def transport(settings, prompt):
        assert len(prompt.encode('utf-8')) <= settings['maxChars']
        data = json.loads(prompt.split('UNTRUSTED_REVIEW_INPUT=', 1)[1])
        seen.extend(data['files'])
        return reply(risk)
    result = run(context, risk, static, config, transport)
    assert result['decision'] == 'APPROVE'
    assert seen == context['files']


def test_thirteen_complete_file_batches_never_reach_the_provider():
    context, risk, static, config = fixture()
    context['files'] = [dict(filename=f'src/file{i}.py', patch='+' + 'x' * 1800) for i in range(13)]
    calls = []
    result = run(context, risk, static, config, lambda *args: calls.append(args))
    assert result['decision'] == 'NOT_VERIFIED'
    assert result['reason'] == 'AI_REVIEW_BATCH_BUDGET_EXCEEDED'
    assert not calls
