import React from 'react';
import { useApp } from '../../context/AppContext';
import { Plus, MessageSquare, Trash2, FileText, Sparkles } from 'lucide-react';

export const ConversationSidebar: React.FC = () => {
  const {
    conversations,
    activeConvId,
    setActiveConvId,
    createNewConversation,
    deleteConversation,
    isSidebarOpen,
    setSidebarOpen,
  } = useApp();

  const handleSelect = (id: string) => {
    setActiveConvId(id);
    setSidebarOpen(false);
  };

  return (
    <>
      {/* Lớp phủ khi mở danh sách trên màn hình hẹp */}
      {isSidebarOpen && (
        <div
          className="lg:hidden fixed inset-0 top-16 bg-slate-900/50 z-20 animate-fade-in"
          onClick={() => setSidebarOpen(false)}
          role="presentation"
        />
      )}

      <aside
        className={`w-64 bg-hds-navy-dark text-slate-200 border-r border-white/10 flex flex-col shrink-0
          fixed lg:static inset-y-16 left-0 z-30 lg:z-auto lg:inset-auto lg:h-full
          transition-transform duration-200 ease-out
          ${isSidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}`}
        aria-label="Danh sách hội thoại"
      >
        {/* Tạo hội thoại mới */}
        <div className="p-3 border-b border-white/10">
          <button
            id="new-chat-btn"
            onClick={createNewConversation}
            className="w-full flex items-center justify-center gap-2 bg-hds-navy hover:bg-hds-navy-light text-white font-medium px-4 py-2.5 rounded-xl transition-colors shadow-sm border border-white/15 text-xs"
          >
            <Plus className="w-4 h-4 text-hds-gold" />
            <span>Cuộc trò chuyện mới</span>
          </button>
        </div>

        {/* Danh sách */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1 min-h-0">
          <div className="px-2 py-1 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
            Lịch sử trò chuyện
          </div>

          {conversations.map((conv) => {
            const isActive = conv.id === activeConvId;
            const hasTempFile = Boolean(conv.temp_file);

            return (
              <div
                key={conv.id}
                className={`group flex items-center gap-1 rounded-xl text-xs transition-colors ${
                  isActive
                    ? 'bg-hds-navy text-white border border-white/20 font-semibold'
                    : 'text-slate-300 hover:bg-white/5 hover:text-white border border-transparent'
                }`}
              >
                <button
                  onClick={() => handleSelect(conv.id)}
                  className="flex items-center gap-2.5 min-w-0 flex-1 p-2.5 text-left"
                  aria-current={isActive ? 'true' : undefined}
                >
                  <MessageSquare
                    className={`w-4 h-4 shrink-0 ${isActive ? 'text-hds-gold' : 'text-slate-400'}`}
                  />
                  <span className="truncate">{conv.title}</span>
                </button>

                {hasTempFile && (
                  <span
                    title={`Tài liệu tạm: ${conv.temp_file?.filename}`}
                    className="bg-hds-gold/20 text-hds-gold-light border border-hds-gold/40 rounded p-1 shrink-0"
                  >
                    <FileText className="w-3 h-3" />
                  </span>
                )}

                <button
                  onClick={() => deleteConversation(conv.id)}
                  className="p-1.5 mr-1 rounded-lg text-slate-500 hover:text-red-300 hover:bg-red-500/15 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity shrink-0"
                  title="Xoá cuộc trò chuyện"
                  aria-label={`Xoá cuộc trò chuyện ${conv.title}`}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            );
          })}
        </div>

        {/* Chân trang */}
        <div className="p-3 border-t border-white/10 text-[11px] text-slate-400 bg-black/20 space-y-1">
          <div className="flex items-center justify-between text-slate-300 font-medium">
            <span className="flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-hds-gold" />
              <span>HDS AI Legal Core</span>
            </span>
            <span className="text-[10px] bg-white/10 text-blue-200 px-1.5 py-0.5 rounded border border-white/15">
              v1.0
            </span>
          </div>
          <p className="text-[10px] text-slate-500 leading-snug">
            Tra cứu và trích dẫn văn bản pháp luật tự động cho HDS Law Firm.
          </p>
        </div>
      </aside>
    </>
  );
};
