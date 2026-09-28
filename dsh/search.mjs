// Use the pinned, unmodified DSH native-search provider. JSON stdin/stdout is
// a local adapter boundary; candidate URLs come only from its structured blocks.
import { DeepSeekSearchProvider } from '@deepseek-ai/dsh-web-search-deepseek';

let input;
try {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  if (!input || typeof input.query !== 'string' || !input.query.trim() ||
      typeof input.apiKey !== 'string' || !input.apiKey) throw new Error('missing query or credential');
  const provider = new DeepSeekSearchProvider(() => ({
    apiKey: input.apiKey,
    apiKeyEnv: 'DEEPSEEK_API_KEY',
    baseURL: 'https://api.deepseek.com/anthropic/v1',
    model: 'deepseek-v4-flash',
    apiVersion: '2023-06-01',
    maxTokens: 1200,
    maxUses: 1,
  }));
  const result = await provider.search({ query: input.query.trim(), maxResults: 10 }, AbortSignal.timeout(45000));
  process.stdout.write(JSON.stringify({ ok: true, provider: 'dsh-deepseek-official', result }));
} catch (error) {
  let code = 'provider_error';
  const message = String(error?.message || error);
  if (/401|403|auth|credential|API key/i.test(message)) code = 'authentication';
  else if (/402|429|quota|balance|limit/i.test(message)) code = 'quota';
  else if (/aborted|timeout|timed out/i.test(message)) code = 'timeout';
  process.stdout.write(JSON.stringify({ ok: false, code, message: message.slice(0, 500) }));
  process.exitCode = 1;
}
