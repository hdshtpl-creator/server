import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { ModelInfo, BenchmarkResult } from '../../types';
import {
  RefreshCw,
  Save,
  RotateCcw,
  Info,
  AlertCircle,
  Loader2,
  Sparkles,
  Cpu,
  Gauge,
  CircleCheck,
  CircleAlert,
} from 'lucide-react';

/**
 * Chọn model sinh câu trả lời trong số các model Ollama đã cài trên máy chủ.
 * Tự quản vòng tải/lưu riêng — độc lập với phần cài đặt còn lại.
 *
 * KHÔNG cho đổi model tạo vector (bge-m3): mọi đoạn tài liệu đã lưu đều theo
 * model đó, đổi sang model khác thì tra cứu ra kết quả sai. Chỉ hiển thị để biết.
 */
const ModelSection: React.FC = () => {
  const { showToast } = useApp();
  const [info, setInfo] = useState<ModelInfo | null>(null);
  const [selected, setSelected] = useState<string>('');
  const [isLoading, setIsLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [bench, setBench] = useState<BenchmarkResult | null>(null);
  const [benching, setBenching] = useState(false);

  const runBenchmark = async () => {
    setBenching(true);
    setBench(null);
    try {
      setBench(await api.benchmarkModel());
    } catch (err: any) {
      setBench({ ok: false, error: err?.message || 'Máy chủ không phản hồi.' });
    } finally {
      setBenching(false);
    }
  };

  const load = async () => {
    setIsLoading(true);
    try {
      const res = await api.getModels();
      setInfo(res);
      setSelected(res.current || '');
    } catch (err: any) {
      showToast(err?.message || 'Không tải được danh sách model.', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      await api.updateSetting('llm_model', selected);
      showToast('Đã đổi model. Có hiệu lực ngay ở câu hỏi tiếp theo.', 'success');
      await load();
    } catch (err: any) {
      showToast(err?.message || 'Không đổi được model.', 'error');
    } finally {
      setSaving(false);
    }
  };

  // Model dùng để SINH câu trả lời: loại model tạo vector ra khỏi lựa chọn.
  const genModels = (info?.available || []).filter(
    (m) => m.split(':')[0] !== (info?.embed_model || '').split(':')[0]
  );
  const dirty = selected !== (info?.current || '');

  return (
    <section className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-5 shadow-sm space-y-4">
      <div className="flex items-center justify-between gap-2 pb-2 border-b border-slate-100 dark:border-slate-800">
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-hds-navy dark:text-blue-400" />
          <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100">Model AI</h3>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1 text-[11px] text-slate-500 dark:text-slate-400 hover:text-hds-navy dark:hover:text-blue-300 transition-colors"
        >
          <RefreshCw className="w-3 h-3" />
          Quét lại
        </button>
      </div>

      {isLoading ? (
        <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 py-2">
          <Loader2 className="w-4 h-4 animate-spin" />
          Đang hỏi máy chủ có những model nào…
        </div>
      ) : !info?.ollama ? (
        <div className="flex items-start gap-2 text-xs text-hds-red dark:text-red-400 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900 rounded-lg p-3">
          <CircleAlert className="w-4 h-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-bold">Chưa kết nối được Ollama trên máy chủ.</p>
            <p className="mt-0.5 leading-relaxed">
              Hỏi đáp AI sẽ báo lỗi cho tới khi Ollama chạy. Trên máy chủ:{' '}
              <code className="font-mono">curl -fsSL https://ollama.com/install.sh | sh</code> rồi{' '}
              <code className="font-mono">ollama pull qwen3:8b bge-m3</code>.
            </p>
          </div>
        </div>
      ) : (
        <>
          <div className="space-y-1">
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300">
              Model sinh câu trả lời
            </label>
            <p className="text-[11px] text-slate-500 dark:text-slate-400">
              Chọn trong số model đã cài trên máy chủ. Model càng lớn càng thông minh nhưng chậm và
              tốn RAM hơn.
            </p>
            <div className="flex flex-col sm:flex-row gap-2 pt-1">
              <select
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
                className="flex-1 px-3 py-2 border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 dark:text-slate-100 rounded-xl text-xs font-medium focus:ring-2 focus:ring-hds-blue focus:outline-none"
              >
                <option value="">— Theo mặc định máy chủ (.env) —</option>
                {genModels.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
              <button
                onClick={save}
                disabled={!dirty || saving}
                className="px-4 py-2 rounded-xl font-bold text-xs text-white shadow-sm flex items-center justify-center gap-1.5 bg-hds-navy hover:bg-hds-navy-light disabled:bg-slate-300 dark:disabled:bg-slate-700 disabled:cursor-not-allowed transition-colors shrink-0"
              >
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                <span>Đổi model</span>
              </button>
            </div>
            {/* Model đang chọn không có trên server → cảnh báo, chat sẽ lỗi */}
            {info.current && !info.current_ready && (
              <p className="text-[11px] text-hds-red dark:text-red-400 flex items-center gap-1 pt-1">
                <CircleAlert className="w-3.5 h-3.5 shrink-0" />
                Model "{info.current}" đang chọn nhưng chưa cài trên máy chủ. Chạy{' '}
                <code className="font-mono">ollama pull {info.current}</code>.
              </p>
            )}
          </div>

          {/* Model tạo vector — chỉ hiển thị, không cho đổi */}
          <div className="flex items-start gap-2 text-[11px] text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-lg p-2.5">
            <Info className="w-3.5 h-3.5 shrink-0 mt-px text-hds-blue" />
            <span>
              Model tạo vector:{' '}
              <code className="font-mono font-semibold">{info.embed_model || '—'}</code>{' '}
              {info.embed_ready ? (
                <CircleCheck className="w-3 h-3 inline text-hds-green" />
              ) : (
                <CircleAlert className="w-3 h-3 inline text-hds-red" />
              )}
              . Cố định — mọi tài liệu đã học đều theo model này, đổi sẽ làm sai kết quả tra cứu.
            </span>
          </div>

          {/* Đo tốc độ phần cứng — cơ sở để biết máy chủ có kham nổi model không */}
          <div className="space-y-2 pt-1 border-t border-slate-100 dark:border-slate-800">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="text-xs font-semibold text-slate-700 dark:text-slate-300">
                  Tốc độ máy chủ
                </p>
                <p className="text-[11px] text-slate-500 dark:text-slate-400">
                  Đo model đang chọn xử lý được bao nhiêu token mỗi giây. Chạy mất vài chục giây.
                </p>
              </div>
              <button
                onClick={runBenchmark}
                disabled={benching}
                className="px-3 py-2 rounded-xl font-bold text-[11px] border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5 shrink-0 transition-colors"
              >
                {benching ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Gauge className="w-3.5 h-3.5" />
                )}
                {benching ? 'Đang đo…' : 'Đo tốc độ'}
              </button>
            </div>

            {bench &&
              (bench.ok ? (
                <div className="text-[11px] bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-lg p-3 space-y-1">
                  <div className="flex justify-between gap-3">
                    <span className="text-slate-500 dark:text-slate-400">
                      Đọc ngữ cảnh (quyết định phần lớn thời gian chờ)
                    </span>
                    <span className="font-mono font-bold text-slate-800 dark:text-slate-100">
                      {bench.read_tok_s ?? '—'} token/giây
                    </span>
                  </div>
                  <div className="flex justify-between gap-3">
                    <span className="text-slate-500 dark:text-slate-400">Viết câu trả lời</span>
                    <span className="font-mono font-bold text-slate-800 dark:text-slate-100">
                      {bench.write_tok_s ?? '—'} token/giây
                    </span>
                  </div>
                  {typeof bench.uoc_tinh_giay === 'number' && (
                    <div
                      className={`flex justify-between gap-3 pt-1.5 border-t border-slate-200 dark:border-slate-700 font-semibold ${
                        bench.uoc_tinh_giay > 90
                          ? 'text-hds-red dark:text-red-400'
                          : bench.uoc_tinh_giay > 45
                            ? 'text-amber-700 dark:text-amber-400'
                            : 'text-hds-green dark:text-green-400'
                      }`}
                    >
                      <span>Ước tính một câu hỏi đầy đủ ngữ cảnh</span>
                      <span className="font-mono">≈ {bench.uoc_tinh_giay}s</span>
                    </div>
                  )}
                  {typeof bench.uoc_tinh_giay === 'number' && bench.uoc_tinh_giay > 90 && (
                    <p className="text-hds-red dark:text-red-400 leading-relaxed pt-0.5">
                      Vượt mốc 100 giây của Cloudflare → sẽ gặp lỗi 524. Hãy chọn model nhẹ hơn,
                      hoặc giảm "Trần ký tự tài liệu" ở phần Tham số bên dưới.
                    </p>
                  )}
                  {typeof bench.write_tok_s === 'number' && bench.write_tok_s < 8 && (
                    <p className="text-amber-700 dark:text-amber-400 leading-relaxed pt-0.5">
                      Dưới 8 token/giây là dấu hiệu model đang chạy bằng CPU chứ không phải GPU.
                      Kiểm tra trên máy chủ bằng <code className="font-mono">ollama ps</code> — cột
                      PROCESSOR phải ghi GPU.
                    </p>
                  )}
                </div>
              ) : (
                <p className="text-[11px] text-hds-red dark:text-red-400">
                  Không đo được: {bench.error}
                </p>
              ))}
          </div>
        </>
      )}
    </section>
  );
};

interface FieldDef {
  key: string;
  label: string;
  hint: string;
  kind: 'textarea' | 'range' | 'number' | 'json';
  /** Giới hạn riêng cho ô số — mỗi tham số một thang khác nhau. */
  min?: number;
  max?: number;
  step?: number;
}

const PROMPT_FIELDS: FieldDef[] = [
  {
    key: 'prompt_internal',
    label: 'Phong cách tư vấn — Nội bộ (luật sư, chuyên viên)',
    hint: 'Áp dụng cho kênh chat của nhân viên HDS. Trả lời chuyên sâu, trích Điều/Khoản.',
    kind: 'textarea',
  },
  {
    key: 'prompt_portal',
    label: 'Phong cách tư vấn — Cổng khách hàng',
    hint: 'Áp dụng cho khách hàng đã ký hợp đồng. Chỉ dùng tài liệu của chính khách đó.',
    kind: 'textarea',
  },
  {
    key: 'prompt_public',
    label: 'Phong cách tư vấn — Website công khai',
    hint: 'Áp dụng cho khách vãng lai. Trả lời khái quát, mời liên hệ luật sư.',
    kind: 'textarea',
  },
];

const PARAM_FIELDS: FieldDef[] = [
  {
    key: 'llm_temperature',
    label: 'Độ sáng tạo của câu trả lời',
    hint: '0 = bám sát tài liệu, chặt chẽ · 1 = phóng khoáng, dễ suy diễn. Pháp lý nên để thấp.',
    kind: 'range',
  },
  {
    key: 'retrieval_top_k',
    label: 'Số đoạn tài liệu tham chiếu mỗi câu hỏi',
    hint: 'Mỗi đoạn thêm vào là mỗi lần trả lời chậm thêm. Khuyến nghị 4–6.',
    kind: 'number',
    min: 1,
    max: 20,
  },
  {
    key: 'context_char_budget',
    label: 'Trần ký tự tài liệu đưa vào mỗi câu hỏi',
    hint: 'Đây là tham số ảnh hưởng tốc độ mạnh nhất. 6000 ký tự ≈ 2000 từ. Tăng gấp đôi là chậm gần gấp đôi.',
    kind: 'number',
    min: 1000,
    max: 40000,
    step: 500,
  },
  {
    key: 'chunk_char_limit',
    label: 'Cắt mỗi đoạn tài liệu còn tối đa (ký tự)',
    hint: 'Chặn một đoạn quá dài chiếm hết chỗ của các đoạn khác.',
    kind: 'number',
    min: 300,
    max: 8000,
    step: 100,
  },
  {
    key: 'min_relevance',
    label: 'Ngưỡng liên quan tối thiểu của đoạn tài liệu',
    hint: 'Đoạn có điểm thấp hơn mức này bị loại — không giúp câu trả lời mà vẫn làm chậm. 0 = không lọc.',
    kind: 'number',
    min: 0,
    max: 0.9,
    step: 0.05,
  },
  {
    key: 'chat_history_turns',
    label: 'Số lượt hỏi-đáp cũ bot nhớ lại',
    hint: 'Giúp bot hiểu "vụ đó", "khách kia". Càng nhiều càng chậm. 0 = tắt trí nhớ hội thoại.',
    kind: 'number',
    min: 0,
    max: 20,
  },
  {
    key: 'llm_num_predict',
    label: 'Trần độ dài câu trả lời (token)',
    hint: 'Chặn trần thời gian trả lời. 700 token ≈ 450 từ, đủ cho câu trả lời gọn.',
    kind: 'number',
    min: 128,
    max: 4096,
    step: 64,
  },
  {
    key: 'llm_num_ctx',
    label: 'Cửa sổ ngữ cảnh của model (token)',
    hint: 'Phải lớn hơn tổng prompt + câu trả lời. Đặt quá to chỉ tốn RAM chứ không giúp gì.',
    kind: 'number',
    min: 2048,
    max: 32768,
    step: 1024,
  },
];

export const AiSettingsTab: React.FC = () => {
  const { showToast } = useApp();
  const [values, setValues] = useState<Record<string, string>>({});
  const [original, setOriginal] = useState<Record<string, string>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [jsonError, setJsonError] = useState<string | null>(null);

  const load = async () => {
    setIsLoading(true);
    try {
      const res = await api.getSettings();
      setValues({ ...res.settings });
      setOriginal({ ...res.settings });
    } catch (err: any) {
      showToast(err?.message || 'Không tải được cài đặt.', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dirty = (key: string) => values[key] !== original[key];

  const patch = (key: string, v: string) => setValues((prev) => ({ ...prev, [key]: v }));

  const save = async (keys: string[]) => {
    const changed = keys.filter(dirty);
    if (changed.length === 0) return;
    setSavingKey(keys.join(','));
    try {
      for (const k of changed) {
        await api.updateSetting(k, values[k]);
        setOriginal((prev) => ({ ...prev, [k]: values[k] }));
      }
      showToast('Đã lưu. Có hiệu lực ngay ở câu hỏi tiếp theo.', 'success');
    } catch (err: any) {
      showToast(err?.message || 'Không lưu được cài đặt.', 'error');
    } finally {
      setSavingKey(null);
    }
  };

  const reset = async (key: string) => {
    try {
      const res = await api.resetSetting(key);
      const v = res.value ?? '';
      patch(key, v);
      setOriginal((prev) => ({ ...prev, [key]: v }));
      showToast('Đã trả về mặc định.', 'success');
    } catch (err: any) {
      showToast(err?.message || 'Không đặt lại được.', 'error');
    }
  };

  const validateJson = (v: string) => {
    try {
      JSON.parse(v);
      setJsonError(null);
      return true;
    } catch (e: any) {
      setJsonError(e?.message || 'JSON không hợp lệ');
      return false;
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-12 text-slate-500 dark:text-slate-400 gap-2 text-sm">
        <RefreshCw className="w-5 h-5 animate-spin text-hds-navy dark:text-blue-400" />
        <span>Đang tải cài đặt AI…</span>
      </div>
    );
  }

  const promptDirty = PROMPT_FIELDS.some((f) => dirty(f.key));
  const paramDirty = PARAM_FIELDS.some((f) => dirty(f.key));
  const driveDirty = dirty('drive_map');

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">Cài đặt AI</h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Phong cách tư vấn của bot, tham số sinh câu trả lời và bản đồ thư mục Drive
          </p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1.5 px-3.5 py-2 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-semibold text-xs rounded-xl transition-colors shrink-0"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Tải lại</span>
        </button>
      </div>

      <div className="p-4 bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-800 rounded-2xl text-amber-900 dark:text-amber-200 text-xs flex items-start gap-3 shadow-sm">
        <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
        <p className="leading-relaxed">
          Sửa phong cách tư vấn ảnh hưởng tới <strong>toàn bộ</strong> câu trả lời của bot. Sau khi
          lưu, hãy thử lại vài câu hỏi để kiểm tra trước khi để nhân viên dùng.
        </p>
      </div>

      {/* Chọn model AI đang chạy trên máy chủ */}
      <ModelSection />

      {/* Phong cách tư vấn */}
      <section className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-5 shadow-sm space-y-4">
        <div className="flex items-center gap-2 pb-2 border-b border-slate-100 dark:border-slate-800">
          <Sparkles className="w-4 h-4 text-hds-gold" />
          <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100">Phong cách tư vấn</h3>
        </div>

        {PROMPT_FIELDS.map((f) => (
          <div key={f.key} className="space-y-1">
            <label className="flex items-center justify-between gap-2 text-xs font-semibold text-slate-700 dark:text-slate-300">
              <span>{f.label}</span>
              {dirty(f.key) && (
                <span className="text-[10px] font-semibold text-amber-700 dark:text-amber-300 bg-amber-100 dark:bg-amber-950 border border-amber-300 dark:border-amber-800 px-1.5 py-0.5 rounded">
                  chưa lưu
                </span>
              )}
            </label>
            <p className="text-[11px] text-slate-500 dark:text-slate-400">{f.hint}</p>
            <textarea
              rows={5}
              value={values[f.key] || ''}
              onChange={(e) => patch(f.key, e.target.value)}
              className={`w-full p-3 border rounded-xl text-xs leading-relaxed focus:ring-2 focus:ring-hds-blue focus:outline-none resize-y dark:bg-slate-800 dark:text-slate-100 ${
                dirty(f.key)
                  ? 'border-amber-400 dark:border-amber-700'
                  : 'border-slate-300 dark:border-slate-700'
              }`}
            />
            <div className="flex justify-end">
              <button
                onClick={() => reset(f.key)}
                className="inline-flex items-center gap-1 text-[11px] text-slate-500 dark:text-slate-400 hover:text-hds-navy dark:hover:text-blue-300 transition-colors"
              >
                <RotateCcw className="w-3 h-3" />
                Về mặc định
              </button>
            </div>
          </div>
        ))}

        <div className="flex justify-end pt-1">
          <button
            onClick={() => save(PROMPT_FIELDS.map((f) => f.key))}
            disabled={!promptDirty || savingKey !== null}
            className="px-4 py-2 rounded-xl font-bold text-xs text-white shadow-sm flex items-center gap-1.5 bg-hds-navy hover:bg-hds-navy-light disabled:bg-slate-300 dark:disabled:bg-slate-700 disabled:cursor-not-allowed transition-colors"
          >
            {savingKey ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            <span>Lưu phong cách tư vấn</span>
          </button>
        </div>
      </section>

      {/* Tham số */}
      <section className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-5 shadow-sm space-y-4">
        <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100 pb-2 border-b border-slate-100 dark:border-slate-800">
          Tham số sinh câu trả lời
        </h3>

        {PARAM_FIELDS.map((f) => (
          <div key={f.key} className="space-y-1">
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300">
              {f.label}
            </label>
            <p className="text-[11px] text-slate-500 dark:text-slate-400">{f.hint}</p>
            {f.kind === 'range' ? (
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.1}
                  value={Number(values[f.key] || 0)}
                  onChange={(e) => patch(f.key, e.target.value)}
                  className="flex-1 accent-[#1f3864]"
                />
                <span className="w-10 text-center text-xs font-mono font-bold text-hds-navy dark:text-blue-300 bg-hds-soft dark:bg-slate-800 rounded px-1 py-0.5">
                  {Number(values[f.key] || 0).toFixed(1)}
                </span>
              </div>
            ) : (
              <input
                type="number"
                min={f.min ?? 0}
                max={f.max}
                step={f.step}
                value={values[f.key] || ''}
                onChange={(e) => patch(f.key, e.target.value)}
                className="w-32 px-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl text-xs focus:ring-2 focus:ring-hds-blue focus:outline-none"
              />
            )}
          </div>
        ))}

        <div className="flex justify-end">
          <button
            onClick={() => save(PARAM_FIELDS.map((f) => f.key))}
            disabled={!paramDirty || savingKey !== null}
            className="px-4 py-2 rounded-xl font-bold text-xs text-white shadow-sm flex items-center gap-1.5 bg-hds-navy hover:bg-hds-navy-light disabled:bg-slate-300 dark:disabled:bg-slate-700 disabled:cursor-not-allowed transition-colors"
          >
            <Save className="w-4 h-4" />
            <span>Lưu tham số</span>
          </button>
        </div>
      </section>

      {/* Bản đồ thư mục Drive */}
      <section className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-5 shadow-sm space-y-3">
        <div className="flex items-center justify-between gap-2 pb-2 border-b border-slate-100 dark:border-slate-800">
          <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100">
            Bản đồ thư mục Drive → nhãn tài liệu
          </h3>
          {driveDirty && (
            <span className="text-[10px] font-semibold text-amber-700 dark:text-amber-300 bg-amber-100 dark:bg-amber-950 border border-amber-300 dark:border-amber-800 px-1.5 py-0.5 rounded">
              chưa lưu
            </span>
          )}
        </div>
        <div className="flex items-start gap-2 text-[11px] text-slate-500 dark:text-slate-400 bg-hds-soft dark:bg-slate-800/60 border border-blue-100 dark:border-slate-700 rounded-lg p-2.5">
          <Info className="w-3.5 h-3.5 shrink-0 mt-px text-hds-blue" />
          <span>
            Quy định thư mục trên Drive tương ứng loại tài liệu và mức truy cập nào. Tên thư mục
            được chuẩn hoá (bỏ số thứ tự, bỏ dấu) trước khi so khớp. Cấu trúc chuẩn xem trong tài
            liệu <code className="font-mono">CAU_TRUC_DRIVE.md</code>.
          </span>
        </div>
        <textarea
          rows={16}
          value={values.drive_map || ''}
          onChange={(e) => {
            patch('drive_map', e.target.value);
            validateJson(e.target.value);
          }}
          spellCheck={false}
          className={`w-full p-3 border rounded-xl text-[11px] font-mono leading-relaxed focus:ring-2 focus:ring-hds-blue focus:outline-none resize-y dark:bg-slate-800 dark:text-slate-100 ${
            jsonError
              ? 'border-red-400 dark:border-red-700'
              : driveDirty
              ? 'border-amber-400 dark:border-amber-700'
              : 'border-slate-300 dark:border-slate-700'
          }`}
        />
        {jsonError && (
          <p className="text-[11px] text-hds-red dark:text-red-400 flex items-center gap-1">
            <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            JSON không hợp lệ: {jsonError}
          </p>
        )}
        <div className="flex justify-between items-center">
          <button
            onClick={() => reset('drive_map')}
            className="inline-flex items-center gap-1 text-[11px] text-slate-500 dark:text-slate-400 hover:text-hds-navy dark:hover:text-blue-300 transition-colors"
          >
            <RotateCcw className="w-3 h-3" />
            Về mặc định
          </button>
          <button
            onClick={() => {
              if (validateJson(values.drive_map || '')) save(['drive_map']);
            }}
            disabled={!driveDirty || Boolean(jsonError) || savingKey !== null}
            className="px-4 py-2 rounded-xl font-bold text-xs text-white shadow-sm flex items-center gap-1.5 bg-hds-navy hover:bg-hds-navy-light disabled:bg-slate-300 dark:disabled:bg-slate-700 disabled:cursor-not-allowed transition-colors"
          >
            <Save className="w-4 h-4" />
            <span>Lưu bản đồ thư mục</span>
          </button>
        </div>
      </section>
    </div>
  );
};
