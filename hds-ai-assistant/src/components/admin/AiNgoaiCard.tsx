import React, { useEffect, useState } from 'react';
import * as api from '../../api';
import type { AiNgoaiCauHinh } from '../../types';
import { Bot, Save, Loader2, CircleCheck, CircleAlert, Info, RefreshCw } from 'lucide-react';

/**
 * ChatGPT làm việc SONG SONG với Qwen — soát đầu ra + "Xem câu trả lời khác".
 * Khoá cài đặt: ai_* (hds-ai/app/settings.py). Khoá API KHÔNG sửa ở đây: nó
 * nằm trong .env của máy chủ, quản trị IT điền tay — thẻ này chỉ báo có/chưa.
 */

type Field = {
  key: string;
  label: string;
  hint: string;
  kind: 'select' | 'text' | 'number';
  options?: Array<{ value: string; label: string }>;
  min?: number;
  max?: number;
  step?: number;
};

const GOI_Y_MODEL = [
  'api:gpt-5-mini',
  'api:gpt-5',
  'api:gpt-5-nano',
  'claude:claude-haiku-4-5',
  'claude:claude-sonnet-5',
];

const NHOM: Array<{ tieu_de: string; fields: Field[] }> = [
  {
    tieu_de: 'Soát câu trả lời',
    fields: [
      {
        key: 'ai_soat_che_do',
        label: 'Chế độ soát',
        hint: 'Model ngoài đọc câu hỏi + câu trả lời + các nguồn được phép, chấm "ổn / cần xem lại / có sai sót" kèm từng vấn đề. Chỉ nhận xét, không sửa câu trả lời.',
        kind: 'select',
        options: [
          { value: 'tat', label: 'Tắt' },
          { value: 'nut', label: 'Bấm nút — người dùng bấm "Soát bằng ChatGPT" khi cần' },
          { value: 'tu_dong', label: 'Tự động — soát ngay sau mỗi câu trả lời' },
        ],
      },
      {
        key: 'ai_soat_model',
        label: 'Model soát',
        hint: 'api:<tên> = OpenAI (ChatGPT); claude:<tên> = Anthropic. Soát là việc đọc–đối chiếu: gpt-5-mini đủ và rẻ (khoảng 0,5–1 cent mỗi lượt).',
        kind: 'text',
      },
      {
        key: 'ai_soat_effort',
        label: 'Độ sâu suy nghĩ khi soát',
        hint: 'Thấp = nhanh, rẻ. Cao = soi kỹ hơn, chậm và đắt hơn.',
        kind: 'select',
        options: [
          { value: 'low', label: 'Thấp (khuyến nghị)' },
          { value: 'medium', label: 'Vừa' },
          { value: 'high', label: 'Cao' },
        ],
      },
      {
        key: 'ai_soat_thay_doc_lai',
        label: 'Bỏ lượt Qwen tự đọc lại khi ChatGPT soát tự động',
        hint: 'Qwen tự đọc lại câu trả lời dài (> 3.500 ký tự), tốn thêm 30–60 giây. Bật: ChatGPT soát thay, câu trả lời về nhanh hơn. Chỉ bỏ khi lượt đó chắc chắn soát được (nguồn trong phạm vi, còn lượt).',
        kind: 'select',
        options: [
          { value: 'false', label: 'Không — giữ lượt Qwen đọc lại' },
          { value: 'true', label: 'Có — ChatGPT soát thay (nhanh hơn)' },
        ],
      },
    ],
  },
  {
    tieu_de: 'Xem câu trả lời khác',
    fields: [
      {
        key: 'ai_khac_bat',
        label: 'Nút "Xem câu trả lời khác"',
        hint: 'Model ngoài trả lời lại cùng câu hỏi, cùng quyền đọc tài liệu của người hỏi, hiện bên dưới để so sánh.',
        kind: 'select',
        options: [
          { value: 'false', label: 'Tắt' },
          { value: 'true', label: 'Bật' },
        ],
      },
      {
        key: 'ai_khac_model',
        label: 'Model trả lời khác',
        hint: 'Nên dùng model mạnh (api:gpt-5) — đây là ý kiến thứ hai. Mỗi lượt gửi khoảng 20–25 nghìn token tài liệu (theo "trần ký tự tài liệu" của nhánh API ngoài).',
        kind: 'text',
      },
      {
        key: 'ai_khac_effort',
        label: 'Độ sâu suy nghĩ khi trả lời khác',
        hint: 'Vừa là cân bằng; Cao cho câu hỏi khó (lâu hơn, đắt hơn).',
        kind: 'select',
        options: [
          { value: 'low', label: 'Thấp' },
          { value: 'medium', label: 'Vừa (khuyến nghị)' },
          { value: 'high', label: 'Cao' },
        ],
      },
    ],
  },
  {
    tieu_de: 'Dữ liệu & chi phí (dùng chung cho cả hai)',
    fields: [
      {
        key: 'cloud_scope',
        label: 'Dữ liệu nào được phép gửi ra ngoài',
        hint: 'Dùng chung với nhánh "API ngoài" ở phần tham số. Nguồn ngoài phạm vi bị BỎ khỏi phần gửi đi; câu trả lời đã trích dẫn nguồn ngoài phạm vi thì không soát. Công nợ/tài chính không bao giờ gửi.',
        kind: 'select',
        options: [
          { value: 'law_only', label: 'Chỉ văn bản pháp luật, án lệ, bản án (an toàn nhất)' },
          { value: 'plus_attachments', label: 'Thêm file nhân viên tự đính kèm' },
          { value: 'all_but_finance', label: 'Mọi thứ trừ công nợ/tài chính' },
        ],
      },
      {
        key: 'ai_ngoai_che_dinh_danh',
        label: 'Che dữ liệu định danh trước khi gửi',
        hint: 'Số CCCD/CMND, điện thoại, email, mã số thuế, số tài khoản và TÊN KHÁCH HÀNG trong kho được thay bằng nhãn [Số định danh], [Khách hàng]… trước khi rời máy chủ.',
        kind: 'select',
        options: [
          { value: 'true', label: 'Bật (khuyến nghị)' },
          { value: 'false', label: 'Tắt — gửi nguyên văn' },
        ],
      },
      {
        key: 'ai_ngoai_tran_luot_thang',
        label: 'Trần số lượt gọi mỗi tháng',
        hint: 'Soát + trả lời khác cộng lại. Hết lượt thì nút báo hết, không âm thầm gọi tiếp. 0 = không giới hạn.',
        kind: 'number',
        min: 0,
        max: 100000,
        step: 50,
      },
      {
        key: 'ai_ngoai_max_tokens',
        label: 'Trần token model ngoài sinh ra mỗi lượt',
        hint: 'Với gpt-5 trần này tính cả phần suy nghĩ — đặt thấp quá thì câu trả lời rỗng. Mặc định 12000.',
        kind: 'number',
        min: 1024,
        max: 64000,
        step: 1000,
      },
    ],
  },
];

export const AI_NGOAI_KEYS = NHOM.flatMap((n) => n.fields.map((f) => f.key));

interface Props {
  values: Record<string, string>;
  dirty: (key: string) => boolean;
  patch: (key: string, v: string) => void;
  save: (keys: string[]) => Promise<void>;
  savingKey: string | null;
}

export const AiNgoaiCard: React.FC<Props> = ({ values, dirty, patch, save, savingKey }) => {
  const [tt, setTt] = useState<AiNgoaiCauHinh | null>(null);
  const [dangTai, setDangTai] = useState(false);

  const taiTrangThai = async () => {
    setDangTai(true);
    try {
      setTt(await api.getAiNgoaiCauHinh(true));
    } finally {
      setDangTai(false);
    }
  };

  useEffect(() => {
    void taiTrangThai();
  }, []);

  const coThayDoi = AI_NGOAI_KEYS.some(dirty);
  const qt = tt?.quan_tri;
  const canKhoaOpenAI = [values.ai_soat_model, values.ai_khac_model].some((m) =>
    (m || '').startsWith('api:')
  );
  const canKhoaClaude = [values.ai_soat_model, values.ai_khac_model].some((m) =>
    (m || '').startsWith('claude:')
  );

  const luu = async () => {
    await save(AI_NGOAI_KEYS);
    // Cấu hình nút trong khung chat được giữ đệm 60 giây — làm tươi ngay.
    await taiTrangThai();
  };

  return (
    <section className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-5 shadow-sm space-y-4">
      <div className="flex items-center justify-between gap-2 pb-2 border-b border-slate-100 dark:border-slate-800">
        <div className="flex items-center gap-2">
          <Bot className="w-4 h-4 text-hds-navy dark:text-blue-400" />
          <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100">
            ChatGPT làm việc song song (soát đầu ra · câu trả lời khác)
          </h3>
        </div>
        <button
          onClick={() => void taiTrangThai()}
          className="flex items-center gap-1 text-[11px] text-slate-500 dark:text-slate-400 hover:text-hds-navy dark:hover:text-blue-300 transition-colors"
        >
          <RefreshCw className={`w-3 h-3 ${dangTai ? 'animate-spin' : ''}`} />
          Kiểm tra lại
        </button>
      </div>

      <div className="flex items-start gap-2 text-[11px] text-slate-600 dark:text-slate-300 bg-hds-soft dark:bg-slate-800/60 border border-blue-100 dark:border-slate-700 rounded-lg p-2.5">
        <Info className="w-3.5 h-3.5 shrink-0 mt-px text-hds-blue" />
        <span className="leading-relaxed">
          Câu trả lời chính vẫn do model trên máy chủ viết. Hai tính năng này gửi dữ liệu{' '}
          <strong>ra khỏi máy chủ HDS</strong> tới nhà cung cấp (OpenAI/Anthropic) và tính tiền theo
          lượt — mặc định tắt, chỉ dành cho nhân viên nội bộ, mọi lượt gọi được ghi vào Nhật ký.
        </span>
      </div>

      {/* Trạng thái khoá + mức dùng tháng này */}
      {qt && (
        <div className="grid sm:grid-cols-2 gap-2 text-[11px]">
          <div
            className={`flex items-start gap-2 rounded-lg border p-2.5 ${
              (canKhoaOpenAI && !qt.co_khoa_openai) || (canKhoaClaude && !qt.co_khoa_claude)
                ? 'border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 text-amber-900 dark:text-amber-200'
                : 'border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-950/30 text-emerald-900 dark:text-emerald-200'
            }`}
          >
            {(canKhoaOpenAI && !qt.co_khoa_openai) || (canKhoaClaude && !qt.co_khoa_claude) ? (
              <CircleAlert className="w-4 h-4 shrink-0" />
            ) : (
              <CircleCheck className="w-4 h-4 shrink-0" />
            )}
            <div className="space-y-0.5 min-w-0">
              <div>
                Khoá OpenAI: <strong>{qt.co_khoa_openai ? 'đã có' : 'chưa có'}</strong> · Khoá
                Anthropic: <strong>{qt.co_khoa_claude ? 'đã có' : 'chưa có'}</strong>
              </div>
              <div className="truncate">Địa chỉ API: {qt.dia_chi_api}</div>
              {canKhoaOpenAI && !qt.co_khoa_openai && (
                <div>
                  IT điền <code className="font-mono">OPENAI_API_KEY=…</code> vào{' '}
                  <code className="font-mono">hds-ai/.env</code> rồi khởi động lại backend — nút
                  trong khung chat chỉ hiện khi có khoá.
                </div>
              )}
            </div>
          </div>
          <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 p-2.5 text-slate-700 dark:text-slate-200 space-y-0.5">
            <div>
              Tháng này: <strong>{qt.su_dung_thang.luot}</strong> lượt
              {qt.tran_luot_thang ? ` / trần ${qt.tran_luot_thang}` : ' (không giới hạn)'}
            </div>
            <div>
              Soát {qt.su_dung_thang.soat} · Trả lời khác {qt.su_dung_thang.khac} · ước tính{' '}
              <strong>${qt.su_dung_thang.usd.toFixed(2)}</strong>
            </div>
            <div className="text-slate-500 dark:text-slate-400">
              Chi phí ước theo bảng giá trong mã nguồn — số thật xem trên trang thanh toán của nhà
              cung cấp.
            </div>
          </div>
        </div>
      )}

      <datalist id="ai-ngoai-goi-y-model">
        {GOI_Y_MODEL.map((m) => (
          <option key={m} value={m} />
        ))}
      </datalist>

      {NHOM.map((nhom) => (
        <div key={nhom.tieu_de} className="space-y-3">
          <h4 className="text-[11px] font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            {nhom.tieu_de}
          </h4>
          {nhom.fields.map((f) => (
            <div key={f.key} className="space-y-1">
              <div className="flex items-center justify-between gap-2">
                <label
                  htmlFor={`ai-ngoai-${f.key}`}
                  className="text-xs font-semibold text-slate-700 dark:text-slate-300"
                >
                  {f.label}
                </label>
                {dirty(f.key) && (
                  <span className="text-[10px] font-semibold text-amber-700 dark:text-amber-300 bg-amber-100 dark:bg-amber-950 border border-amber-300 dark:border-amber-800 px-1.5 py-0.5 rounded">
                    chưa lưu
                  </span>
                )}
              </div>
              <p className="text-[11px] text-slate-500 dark:text-slate-400">{f.hint}</p>
              {f.kind === 'select' ? (
                <select
                  id={`ai-ngoai-${f.key}`}
                  value={values[f.key] ?? ''}
                  onChange={(e) => patch(f.key, e.target.value)}
                  className="w-full max-w-md px-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl text-xs focus:ring-2 focus:ring-hds-blue focus:outline-none"
                >
                  {(f.options ?? []).map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              ) : f.kind === 'text' ? (
                <input
                  id={`ai-ngoai-${f.key}`}
                  type="text"
                  list="ai-ngoai-goi-y-model"
                  value={values[f.key] ?? ''}
                  onChange={(e) => patch(f.key, e.target.value.trim())}
                  className="w-full max-w-md px-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl text-xs font-mono focus:ring-2 focus:ring-hds-blue focus:outline-none"
                />
              ) : (
                <input
                  id={`ai-ngoai-${f.key}`}
                  type="number"
                  min={f.min}
                  max={f.max}
                  step={f.step}
                  value={values[f.key] ?? ''}
                  onChange={(e) => patch(f.key, e.target.value)}
                  className="w-32 px-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl text-xs focus:ring-2 focus:ring-hds-blue focus:outline-none"
                />
              )}
            </div>
          ))}
        </div>
      ))}

      <div className="flex justify-end">
        <button
          onClick={() => void luu()}
          disabled={!coThayDoi || savingKey !== null}
          className="px-4 py-2 rounded-xl font-bold text-xs text-white shadow-sm flex items-center gap-1.5 bg-hds-navy hover:bg-hds-navy-light disabled:bg-slate-300 dark:disabled:bg-slate-700 disabled:cursor-not-allowed transition-colors"
        >
          {savingKey !== null ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Save className="w-4 h-4" />
          )}
          <span>Lưu cài đặt ChatGPT</span>
        </button>
      </div>
    </section>
  );
};
