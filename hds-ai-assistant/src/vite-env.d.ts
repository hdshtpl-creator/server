/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_ENABLE_MOCK_MODE?: string;
  /** Dấu bản build, deploy/update.sh đặt = <commit ngắn>-<ngàytháng.giờphút>. */
  readonly VITE_BUILD_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
