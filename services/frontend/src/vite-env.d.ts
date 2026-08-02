/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ADMIN_TOKEN?: string;
  readonly VITE_SPATIAL_SCOPE_ENABLED?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
