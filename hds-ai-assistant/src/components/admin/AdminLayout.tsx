import React from 'react';
import { useApp } from '../../context/AppContext';
import { OverviewTab } from './OverviewTab';
import { DocumentReviewTab } from './DocumentReviewTab';
import { LearnReviewTab } from './LearnReviewTab';
import { MethodTemplatesTab } from './MethodTemplatesTab';
import { UserManagementTab } from './UserManagementTab';
import { LearnedDocsTab } from './LearnedDocsTab';
import { Client360Tab } from './Client360Tab';
import { BrowseDocsTab } from './BrowseDocsTab';
import { AiSettingsTab } from './AiSettingsTab';
import { FeedbackReviewTab } from './FeedbackReviewTab';
import {
  LayoutDashboard,
  FileCheck2,
  MessageSquareText,
  Boxes,
  Users,
  BookOpen,
  ShieldAlert,
  Users2,
  Search,
  SlidersHorizontal,
  MessageSquareWarning,
} from 'lucide-react';

type TabDef = {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  group: 'operate' | 'knowledge';
  adminOnly?: boolean;
};

const TABS: TabDef[] = [
  { id: 'overview', label: 'Tổng quan', icon: LayoutDashboard, group: 'operate' },
  { id: 'clients_360', label: 'Hồ sơ khách 360°', icon: Users2, group: 'operate' },
  { id: 'learn', label: 'Duyệt hội thoại AI', icon: MessageSquareText, group: 'operate' },
  { id: 'feedback', label: 'Duyệt báo cáo', icon: MessageSquareWarning, group: 'operate' },
  { id: 'users', label: 'Người dùng & Phòng ban', icon: Users, group: 'operate', adminOnly: true },
  { id: 'settings', label: 'Cài đặt AI', icon: SlidersHorizontal, group: 'operate', adminOnly: true },

  { id: 'browse_docs', label: 'Tra cứu tài liệu', icon: Search, group: 'knowledge' },
  { id: 'review', label: 'Duyệt nhãn tài liệu', icon: FileCheck2, group: 'knowledge' },
  { id: 'documents', label: 'Kho tài liệu đã học', icon: BookOpen, group: 'knowledge' },
  { id: 'methods', label: 'Mẫu phương pháp', icon: Boxes, group: 'knowledge' },
];

const GROUP_LABEL: Record<TabDef['group'], string> = {
  operate: 'Vận hành',
  knowledge: 'Tri thức',
};

export const AdminLayout: React.FC = () => {
  const { adminTab, setAdminTab, currentUser } = useApp();
  const isAdmin = currentUser?.role === 'admin';

  const tabs = TABS.filter((t) => !t.adminOnly || isAdmin);

  const renderTabButton = (tab: TabDef) => {
    const Icon = tab.icon;
    const isActive = adminTab === tab.id;
    return (
      <button
        key={tab.id}
        id={`admin-tab-${tab.id}`}
        role="tab"
        aria-selected={isActive}
        onClick={() => setAdminTab(tab.id)}
        className={`flex items-center gap-2 px-3.5 py-2.5 rounded-xl font-semibold text-xs whitespace-nowrap shrink-0 transition-colors ${
          isActive
            ? 'bg-hds-navy text-hds-gold shadow-sm'
            : 'text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800'
        }`}
      >
        <Icon className={`w-4 h-4 ${isActive ? '' : 'text-slate-400'}`} />
        <span>{tab.label}</span>
      </button>
    );
  };

  return (
    <div className="flex-1 bg-hds-soft dark:bg-slate-950 p-4 sm:p-6 lg:p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        {!currentUser?.can_review && currentUser?.role !== 'admin' && (
          <div className="p-4 bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-800 rounded-2xl text-amber-900 dark:text-amber-200 flex items-start gap-3 text-xs shadow-sm">
            <ShieldAlert className="w-5 h-5 shrink-0 mt-0.5" />
            <div>
              <p className="font-bold">Chế độ xem hạn chế</p>
              <p className="mt-0.5 leading-relaxed">
                Tài khoản <strong>{currentUser?.full_name}</strong> chưa được cấp quyền kiểm duyệt (
                <code className="font-mono">can_review = false</code>). Các thao tác duyệt tài liệu,
                duyệt hội thoại và xem kho tri thức sẽ bị backend từ chối với mã 403. Liên hệ quản
                trị viên nếu bạn cần quyền này.
              </p>
            </div>
          </div>
        )}

        <div className="bg-white dark:bg-slate-900 p-2.5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-2">
          {(['operate', 'knowledge'] as const).map((group) => {
            const groupTabs = tabs.filter((t) => t.group === group);
            if (groupTabs.length === 0) return null;
            return (
              <div key={group}>
                <div className="px-2 pb-1 text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">
                  {GROUP_LABEL[group]}
                </div>
                <div
                  className="flex gap-1 overflow-x-auto no-scrollbar"
                  role="tablist"
                  aria-label={GROUP_LABEL[group]}
                >
                  {groupTabs.map(renderTabButton)}
                </div>
              </div>
            );
          })}
        </div>

        <div role="tabpanel">
          {adminTab === 'overview' && <OverviewTab />}
          {adminTab === 'clients_360' && <Client360Tab />}
          {adminTab === 'learn' && <LearnReviewTab />}
          {adminTab === 'feedback' && <FeedbackReviewTab />}
          {adminTab === 'users' && isAdmin && <UserManagementTab />}
          {adminTab === 'settings' && isAdmin && <AiSettingsTab />}
          {adminTab === 'browse_docs' && <BrowseDocsTab />}
          {adminTab === 'review' && <DocumentReviewTab />}
          {adminTab === 'documents' && <LearnedDocsTab />}
          {adminTab === 'methods' && <MethodTemplatesTab />}
        </div>
      </div>
    </div>
  );
};
