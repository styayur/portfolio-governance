import json
import subprocess
import sys
from pathlib import Path


def test_cli_logs_counts_without_untrusted_finding_text(tmp_path):
    secret_marker = 'ghp_' + 'x' * 40
    filename = f'private-{secret_marker}.py'
    context = {
        'headSha': 'a' * 40,
        'body': 'Check that sensitive finding details stay out of console logs.',
        'files': [{'filename': filename, 'patch': '+' + secret_marker}],
    }
    risk = {'headSha': context['headSha'], 'risk': 'R0'}
    context_path = tmp_path / 'context.json'
    risk_path = tmp_path / 'risk.json'
    output_path = tmp_path / 'report.json'
    context_path.write_text(json.dumps(context))
    risk_path.write_text(json.dumps(risk))
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).parents[1] / 'scripts/independent_review.py'),
         '--context', str(context_path), '--risk', str(risk_path), '--output', str(output_path)],
        capture_output=True, text=True, check=True,
    )
    summary = json.loads(completed.stdout)
    report = json.loads(output_path.read_text())
    assert summary['decision'] == report['decision'] == 'BLOCK'
    assert summary['blockerCount'] == len(report['blockers']) == 1
    assert summary['manualReviewReasonCount'] == len(report['manualReviewReasons'])
    assert summary['warningCount'] == len(report['warnings'])
    assert filename in report['blockers'][0]
    assert secret_marker not in completed.stdout + completed.stderr
    assert 'possible github-token' not in completed.stdout
