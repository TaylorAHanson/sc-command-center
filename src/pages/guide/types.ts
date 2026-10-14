import type React from 'react';
import type { LucideIcon } from 'lucide-react';

export type GuideGroup = 'start' | 'use' | 'build' | 'admin' | 'reference';

export const GROUP_TITLES: Record<GuideGroup, string> = {
  start: 'Get started',
  use: 'Using the Command Center',
  build: 'Building',
  admin: 'Administering',
  reference: 'Reference',
};

export interface GuideSection {
  /** The address of the section: `#/user-guide/<id>`. Keep it stable once shipped. */
  id: string;
  group: GuideGroup;
  title: string;
  /** One line shown under the title and in search results. */
  summary: string;
  icon: LucideIcon;
  /** Words people search for that the page may not use ("sign in" for access). */
  keywords?: string;
  Body: React.FC;
}
