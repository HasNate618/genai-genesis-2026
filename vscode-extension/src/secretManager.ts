import * as vscode from 'vscode';

const KEY_NAMES = {
  gemini: 'agentic-army.gemini-api-key',
  moorcheh: 'agentic-army.moorcheh-api-key',
} as const;

type KeyService = keyof typeof KEY_NAMES;

export class SecretManager {
  constructor(private readonly context: vscode.ExtensionContext) {}

  async store(service: KeyService, value: string): Promise<void> {
    await this.context.secrets.store(KEY_NAMES[service], value);
  }

  async get(service: KeyService): Promise<string | undefined> {
    return this.context.secrets.get(KEY_NAMES[service]);
  }

  async delete(service: KeyService): Promise<void> {
    await this.context.secrets.delete(KEY_NAMES[service]);
  }

  async getAll(): Promise<{ gemini?: string; moorcheh?: string }> {
    const [gemini, moorcheh] = await Promise.all([
      this.get('gemini'),
      this.get('moorcheh'),
    ]);
    return { gemini, moorcheh };
  }

  async storeAll(keys: { gemini?: string; moorcheh?: string }): Promise<void> {
    const ops: Promise<void>[] = [];
    if (keys.gemini !== undefined) {
      ops.push(this.store('gemini', keys.gemini));
    }
    if (keys.moorcheh !== undefined) {
      ops.push(this.store('moorcheh', keys.moorcheh));
    }
    await Promise.all(ops);
  }
}
