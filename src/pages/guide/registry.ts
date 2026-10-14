import type { GuideSection } from './types';
import { section as overview } from './sections/overview';
import { section as quickstart } from './sections/quickstart';
import { section as views } from './sections/views';
import { section as widgets } from './sections/widgets';
import { section as assistant } from './sections/assistant';
import { section as widgetStudio } from './sections/widget-studio';
import { section as agentStudio } from './sections/agent-studio';
import { section as roles } from './sections/roles';
import { section as access } from './sections/access';
import { section as promotion } from './sections/promotion';
import { section as settings } from './sections/settings';
import { section as migration } from './sections/migration';
import { section as actionLogs } from './sections/action-logs';
import { section as reference } from './sections/reference';
import { section as troubleshooting } from './sections/troubleshooting';

// The order here is the order of the sidebar, within each group.
export const SECTIONS: GuideSection[] = [
  overview,
  quickstart,
  views,
  widgets,
  assistant,
  widgetStudio,
  agentStudio,
  roles,
  access,
  promotion,
  settings,
  migration,
  actionLogs,
  reference,
  troubleshooting,
];
