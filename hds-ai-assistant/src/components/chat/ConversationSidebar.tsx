import React, { useEffect, useRef, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { ChatSearchHit } from '../../types';
import {
  Search,
  StickyNote,
  Trash2,
  Plus,
  X,
  Loader2,
  CornerDownLeft,
  MessageSquarePlus,
  MessageSquare,
  Pencil,
  Check,
} from 'lucide-react';

/**
 * Cột trái của trợ lý — mô hình NHIỀU hội thoại (như ChatGPT/Claude):
 *   · nút "Cuộc trò chuyện mới",
 *   · danh sách hội thoại (chọn / đổi tên / xoá),
 *   · ô Tìm kiếm xuyên mọi hội thoại,
 *   · Ghi chú cá nhân.
 */
export const ConversationSidebar: React.FC = () => {
  const {
    isSidebarOpen,
    setSidebarOpen,
    conversations,
    activeConversation,
    newConversation,
    selectConversation,
    renameConversation,
    deleteConversation,
    notes,
    reloadNotes,
    saveNote,
    removeNote,
    showToast,
    isChatStreaming,
  } = useApp();

  const [query, setQuery] = useState('');
  const [results, setResults] = useState<ChatSearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);

  const [noteText, setNoteText] = useState('');
  const [savingNote, setSavingNote] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const activeServerId = activeConversation?.server_id;

  useEffect(() => {
    reloadNotes();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Tìm kiếm có giãn cách (debounce) để không gọi backend mỗi phím
  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    const q = query.trim();
    if (q.length < 2) {
      setResults([]);
      setSearched(false);
      return;
    }
    searchTimer.current = setTimeout(async () => {
      setSearching(true);
      try {
        setResults(await api.searchChat(q));
      } catch (err: any) {
        showToast(err?.message || 'Không tìm được.', 'error');
      } finally {
        setSearching(false);
        setSearched(true);
      }
    }, 350);
    return () => {
      if (searchTimer.current) clearTimeout(searchTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  const jumpToMessage = (id: number) => {
    const el = document.getElementById(`chatmsg-${id}`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('ring-2', 'ring-hds-gold');
      setTimeout(() => el.classList.remove('ring-2', 'ring-hds-gold'), 1600);
      setSidebarOpen(false);
    } else {
      showToast('Đoạn này nằm ngoài phần đang hiển thị.', 'info');
    }
  };

  // Bấm kết quả tìm: cùng hội thoại thì nhảy thẳng, khác thì mở đúng hội thoại rồi nhảy
  const openHit = (hit: ChatSearchHit) => {
    if (isChatStreaming && hit.conversation_id !== activeServerId) {
      showToast('Hãy chờ câu trả lời hiện tại được lưu xong.', 'info');
      return;
    }
    if (hit.conversation_id && hit.conversation_id !== activeServerId) {
      selectConversation(hit.conversation_id, hit.id).catch(() =>
        showToast('Không mở được hội thoại này.', 'error')
      );
    } else {
      jumpToMessage(hit.id);
    }
  };

  const handleAddNote = async () => {
    const content = noteText.trim();
    if (!content) return;
    setSavingNote(true);
    try {
      await saveNote(content);
      setNoteText('');
    } catch (err: any) {
      showToast(err?.message || 'Không lưu được ghi chú.', 'error');
    } finally {
      setSavingNote(false);
    }
  };

  const startRename = (id: number, title: string) => {
    setEditingId(id);
    setEditTitle(title);
  };

  const commitRename = async () => {
    if (editingId == null) return;
    const t = editTitle.trim();
    const id = editingId;
    setEditingId(null);
    if (!t) return;
    try {
      await renameConversation(id, t);
    } catch (err: any) {
      showToast(err?.message || 'Không đổi được tên.', 'error');
    }
  };

  const handleDelete = async (id: number, title: string) => {
    if (isChatStreaming) {
      showToast('Hãy chờ câu trả lời hiện tại được lưu xong.', 'info');
      return;
    }
    if (!window.confirm(`Xoá hội thoại "${title}"? Toàn bộ tin nhắn trong đó sẽ mất.`)) return;
    try {
      await deleteConversation(id);
    } catch (err: any) {
      showToast(err?.message || 'Không xoá được.', 'error');
    }
  };

  return (
    <>
      {isSidebarOpen && (
        <div
          className="lg:hidden fixed inset-0 top-16 bg-slate-900/50 z-20 animate-fade-in"
          onClick={() => setSidebarOpen(false)}
          role="presentation"
        />
      )}

      <aside
        className={`w-72 bg-hds-navy-dark text-slate-200 border-r border-white/10 flex flex-col shrink-0
          fixed lg:static top-16 bottom-0 left-0 z-30 lg:z-auto lg:inset-auto lg:h-full
          transition-transform duration-200 ease-out
          ${isSidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}`}
        aria-label="Bảng trợ lý"
      >
        {/* Cuộc trò chuyện mới + tìm kiếm */}
        <div className="p-3 border-b border-white/10 space-y-2">
          <button
            onClick={newConversation}
            disabled={isChatStreaming}
            title={isChatStreaming ? 'Hãy chờ câu trả lời hiện tại lưu xong' : undefined}
            className="w-full flex items-center justify-center gap-2 bg-hds-navy hover:bg-hds-navy-light text-hds-gold font-semibold text-xs px-3 py-2.5 rounded-xl border border-hds-gold/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <MessageSquarePlus className="w-4 h-4" />
            Cuộc trò chuyện mới
          </button>

          <div className="relative">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Tìm trong mọi hội thoại…"
              aria-label="Tìm trong lịch sử trò chuyện"
              className="w-full pl-9 pr-3 py-2 bg-white/5 border border-white/10 rounded-xl text-xs text-slate-100 placeholder-slate-400 focus:ring-2 focus:ring-hds-gold/60 focus:outline-none"
            />
          </div>

          {searching && (
            <div className="flex items-center gap-1.5 text-[11px] text-slate-400 px-1">
              <Loader2 className="w-3 h-3 animate-spin" />
              Đang tìm…
            </div>
          )}

          {searched && !searching && (
            <div className="space-y-1 max-h-48 overflow-y-auto">
              {results.length === 0 ? (
                <p className="text-[11px] text-slate-500 px-1 py-1">Không thấy đoạn nào khớp.</p>
              ) : (
                results.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => openHit(r)}
                    className="w-full text-left bg-white/5 hover:bg-white/10 rounded-lg p-2 transition-colors"
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="text-[9px] font-bold uppercase tracking-wider text-hds-gold/80">
                        {r.role === 'user' ? 'Bạn hỏi' : 'Trợ lý'}
                      </span>
                      {r.conversation_title && (
                        <span className="text-[9px] text-slate-400 truncate max-w-[55%]">
                          {r.conversation_title}
                        </span>
                      )}
                    </span>
                    <span className="block text-[11px] text-slate-300 leading-snug line-clamp-2 mt-0.5">
                      {r.content}
                    </span>
                  </button>
                ))
              )}
            </div>
          )}
        </div>

        {/* Danh sách hội thoại */}
        <div className="flex-1 flex flex-col min-h-0">
          <div className="px-3 pt-3 pb-1 flex items-center gap-1.5 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
            <MessageSquare className="w-3.5 h-3.5 text-hds-gold" />
            Cuộc trò chuyện
          </div>
          <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-0.5 min-h-0">
            {conversations.length === 0 ? (
              <p className="text-[11px] text-slate-500 px-2 py-2 leading-relaxed">
                Chưa có hội thoại nào. Bấm "Cuộc trò chuyện mới" và đặt câu hỏi để bắt đầu.
              </p>
            ) : (
              conversations.map((c) => {
                const active = c.id === activeServerId;
                return (
                  <div
                    key={c.id}
                    className={`group rounded-lg flex items-center gap-1 transition-colors ${
                      active ? 'bg-hds-gold/15 border border-hds-gold/30' : 'hover:bg-white/[0.07] border border-transparent'
                    }`}
                  >
                    {editingId === c.id ? (
                      <input
                        autoFocus
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        onBlur={commitRename}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') commitRename();
                          if (e.key === 'Escape') setEditingId(null);
                        }}
                        className="flex-1 min-w-0 bg-white/10 text-[12px] text-slate-100 px-2 py-1.5 rounded-lg focus:outline-none focus:ring-2 focus:ring-hds-gold/60 mx-1 my-0.5"
                      />
                    ) : (
                      <button
                        onClick={() => {
                          if (isChatStreaming && c.id !== activeServerId) {
                            showToast('Hãy chờ câu trả lời hiện tại được lưu xong.', 'info');
                            return;
                          }
                          selectConversation(c.id).catch(() =>
                            showToast('Không mở được hội thoại.', 'error')
                          );
                        }}
                        className="flex-1 min-w-0 text-left px-2.5 py-2"
                        title={c.title}
                      >
                        <span
                          className={`block text-[12px] truncate ${
                            active ? 'text-hds-gold font-semibold' : 'text-slate-200'
                          }`}
                        >
                          {c.title}
                        </span>
                        <span className="block text-[9px] text-slate-500 mt-0.5">
                          {c.message_count} tin nhắn
                        </span>
                      </button>
                    )}

                    {editingId === c.id ? (
                      <button
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={commitRename}
                        className="p-1.5 mr-1 rounded text-hds-gold hover:bg-white/10"
                        title="Lưu tên"
                      >
                        <Check className="w-3.5 h-3.5" />
                      </button>
                    ) : (
                      <span className="flex items-center pr-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                        <button
                          onClick={() => startRename(c.id, c.title)}
                          className="p-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-white/10"
                          title="Đổi tên"
                          aria-label="Đổi tên hội thoại"
                        >
                          <Pencil className="w-3 h-3" />
                        </button>
                        <button
                          onClick={() => handleDelete(c.id, c.title)}
                          className="p-1.5 rounded text-slate-400 hover:text-red-300 hover:bg-red-500/15"
                          title="Xoá hội thoại"
                          aria-label="Xoá hội thoại"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </span>
                    )}
                  </div>
                );
              })
            )}
          </div>

          {/* Ghi chú cá nhân — khối ở dưới, cuộn riêng */}
          <div className="border-t border-white/10 flex flex-col max-h-[38%]">
            <div className="px-3 pt-2.5 pb-1 flex items-center gap-1.5 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
              <StickyNote className="w-3.5 h-3.5 text-hds-gold" />
              Ghi chú của tôi
            </div>

            <div className="px-3 pb-2">
              <div className="flex items-start gap-1.5">
                <textarea
                  rows={2}
                  value={noteText}
                  onChange={(e) => setNoteText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                      e.preventDefault();
                      handleAddNote();
                    }
                  }}
                  placeholder="Ghi nhanh điều cần nhớ… (Ctrl+Enter để lưu)"
                  className="flex-1 px-2.5 py-1.5 bg-white/5 border border-white/10 rounded-lg text-[11px] text-slate-100 placeholder-slate-400 focus:ring-2 focus:ring-hds-gold/60 focus:outline-none resize-none"
                />
                <button
                  onClick={handleAddNote}
                  disabled={!noteText.trim() || savingNote}
                  title="Lưu ghi chú"
                  className="p-2 bg-hds-navy hover:bg-hds-navy-light rounded-lg border border-white/15 shrink-0 disabled:opacity-40 transition-colors"
                >
                  {savingNote ? (
                    <Loader2 className="w-4 h-4 animate-spin text-hds-gold" />
                  ) : (
                    <Plus className="w-4 h-4 text-hds-gold" />
                  )}
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-1.5 min-h-0">
              {notes.length === 0 ? (
                <p className="text-[11px] text-slate-500 px-1 py-1 leading-relaxed">
                  Chưa có ghi chú. Ghi ở trên, hoặc bấm "Lưu note" dưới một câu trả lời.
                </p>
              ) : (
                notes.map((n) => (
                  <div
                    key={n.id}
                    className="group bg-white/5 hover:bg-white/[0.08] border border-white/10 rounded-lg p-2.5 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-[11px] text-slate-200 leading-relaxed break-words whitespace-pre-wrap flex-1">
                        {n.content}
                      </p>
                      <button
                        onClick={() => removeNote(n.id).catch(() => showToast('Không xoá được.', 'error'))}
                        className="p-1 rounded text-slate-500 hover:text-red-300 hover:bg-red-500/15 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-all shrink-0"
                        title="Xoá ghi chú"
                        aria-label="Xoá ghi chú"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                    <div className="flex items-center gap-2 mt-1.5">
                      <span className="text-[9px] text-slate-500 font-mono">{n.created_at}</span>
                      {n.source_message_id && (
                        <button
                          onClick={() => jumpToMessage(n.source_message_id as number)}
                          className="text-[9px] text-hds-gold/80 hover:text-hds-gold inline-flex items-center gap-0.5"
                          title="Tới câu trả lời gốc"
                        >
                          <CornerDownLeft className="w-2.5 h-2.5" />
                          Từ câu trả lời
                        </button>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Nút đóng trên mobile */}
        <button
          onClick={() => setSidebarOpen(false)}
          className="lg:hidden absolute top-2 right-2 p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/10"
          aria-label="Đóng bảng trợ lý"
        >
          <X className="w-4 h-4" />
        </button>
      </aside>
    </>
  );
};
