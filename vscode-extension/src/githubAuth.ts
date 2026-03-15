import * as vscode from 'vscode';

const GITHUB_SCOPES = ['repo', 'read:user'];
const GITHUB_AUTH_TIMEOUT_MS = 45000;

function withTimeout<T>(promise: PromiseLike<T>, timeoutMs: number, timeoutMessage: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(timeoutMessage)), timeoutMs);
    Promise.resolve(promise).then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (err) => {
        clearTimeout(timer);
        reject(err);
      }
    );
  });
}

export async function getGitHubAccessToken(): Promise<string> {
  const existingSession = await vscode.authentication.getSession(
    'github',
    GITHUB_SCOPES,
    { createIfNone: false }
  );

  if (existingSession?.accessToken) {
    return existingSession.accessToken;
  }

  const newSession = await withTimeout(
    vscode.authentication.getSession('github', GITHUB_SCOPES, { createIfNone: true }),
    GITHUB_AUTH_TIMEOUT_MS,
    'GitHub sign-in timed out. Complete VS Code GitHub auth and retry.'
  );

  if (!newSession?.accessToken) {
    throw new Error('GitHub sign-in did not return an access token.');
  }

  return newSession.accessToken;
}
