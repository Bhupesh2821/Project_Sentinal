// Scope the provider CLI's documented auth/cache home to this project process.
// HOME and system configuration are never changed. Authentication is unchanged.
import os from 'node:os';
import { syncBuiltinESMExports } from 'node:module';
import { fileURLToPath } from 'node:url';
const taskStorage = fileURLToPath(new URL('../config/connected/base44-home/', import.meta.url));
os.homedir = () => taskStorage;
syncBuiltinESMExports();
