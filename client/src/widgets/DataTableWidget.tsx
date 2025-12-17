import React, { useMemo, useState } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  flexRender,
  type ColumnDef,
  type ColumnFiltersState,
  type SortingState,
  type VisibilityState,
} from '@tanstack/react-table';
import { Search, ChevronDown, ChevronUp, ChevronsUpDown, X, Eye } from 'lucide-react';
import type { WidgetProps } from '../widgetRegistry';

// Mock data for supply chain supplier performance
interface SupplierData {
  id: string;
  supplierName: string;
  onTimeDelivery: number;
  qualityScore: number;
  costRating: string;
  status: string;
  totalOrders: number;
  region: string;
  lastOrderDate: string;
}

const mockData: SupplierData[] = [
  {
    id: '1',
    supplierName: 'TSMC Manufacturing',
    onTimeDelivery: 98.5,
    qualityScore: 9.2,
    costRating: 'A',
    status: 'Active',
    totalOrders: 1247,
    region: 'Asia-Pacific',
    lastOrderDate: '2024-01-15',
  },
  {
    id: '2',
    supplierName: 'Samsung Electronics',
    onTimeDelivery: 96.8,
    qualityScore: 9.0,
    costRating: 'A',
    status: 'Active',
    totalOrders: 892,
    region: 'Asia-Pacific',
    lastOrderDate: '2024-01-14',
  },
  {
    id: '3',
    supplierName: 'Foxconn Technology',
    onTimeDelivery: 94.2,
    qualityScore: 8.7,
    costRating: 'B',
    status: 'Active',
    totalOrders: 654,
    region: 'Asia-Pacific',
    lastOrderDate: '2024-01-13',
  },
  {
    id: '4',
    supplierName: 'Intel Corporation',
    onTimeDelivery: 97.1,
    qualityScore: 9.1,
    costRating: 'A',
    status: 'Active',
    totalOrders: 523,
    region: 'North America',
    lastOrderDate: '2024-01-12',
  },
  {
    id: '5',
    supplierName: 'Micron Technology',
    onTimeDelivery: 95.5,
    qualityScore: 8.9,
    costRating: 'B',
    status: 'Active',
    totalOrders: 412,
    region: 'North America',
    lastOrderDate: '2024-01-11',
  },
  {
    id: '6',
    supplierName: 'SK Hynix',
    onTimeDelivery: 93.8,
    qualityScore: 8.5,
    costRating: 'B',
    status: 'Active',
    totalOrders: 389,
    region: 'Asia-Pacific',
    lastOrderDate: '2024-01-10',
  },
  {
    id: '7',
    supplierName: 'Broadcom Inc.',
    onTimeDelivery: 99.2,
    qualityScore: 9.4,
    costRating: 'A',
    status: 'Active',
    totalOrders: 287,
    region: 'North America',
    lastOrderDate: '2024-01-09',
  },
  {
    id: '8',
    supplierName: 'NXP Semiconductors',
    onTimeDelivery: 92.1,
    qualityScore: 8.3,
    costRating: 'C',
    status: 'Review',
    totalOrders: 198,
    region: 'Europe',
    lastOrderDate: '2024-01-08',
  },
  {
    id: '9',
    supplierName: 'STMicroelectronics',
    onTimeDelivery: 96.3,
    qualityScore: 8.8,
    costRating: 'B',
    status: 'Active',
    totalOrders: 156,
    region: 'Europe',
    lastOrderDate: '2024-01-07',
  },
  {
    id: '10',
    supplierName: 'MediaTek Inc.',
    onTimeDelivery: 94.7,
    qualityScore: 8.6,
    costRating: 'B',
    status: 'Active',
    totalOrders: 234,
    region: 'Asia-Pacific',
    lastOrderDate: '2024-01-06',
  },
];

export const DataTableWidget: React.FC<WidgetProps> = () => {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});
  const [globalFilter, setGlobalFilter] = useState('');
  const [showColumnMenu, setShowColumnMenu] = useState(false);

  const columns = useMemo<ColumnDef<SupplierData>[]>(
    () => [
      {
        accessorKey: 'supplierName',
        header: 'Supplier Name',
        cell: (info) => <div className="font-medium text-qualcomm-navy">{info.getValue() as string}</div>,
      },
      {
        accessorKey: 'onTimeDelivery',
        header: 'On-Time Delivery %',
        cell: (info) => {
          const value = info.getValue() as number;
          return (
            <div className="flex items-center gap-2">
              <span>{value.toFixed(1)}%</span>
              <div className="w-16 h-2 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className="h-full bg-qualcomm-blue"
                  style={{ width: `${value}%` }}
                />
              </div>
            </div>
          );
        },
      },
      {
        accessorKey: 'qualityScore',
        header: 'Quality Score',
        cell: (info) => {
          const value = info.getValue() as number;
          const color = value >= 9 ? 'text-green-600' : value >= 8.5 ? 'text-yellow-600' : 'text-red-600';
          return <span className={`font-semibold ${color}`}>{value.toFixed(1)}</span>;
        },
      },
      {
        accessorKey: 'costRating',
        header: 'Cost Rating',
        cell: (info) => {
          const value = info.getValue() as string;
          const colorMap: Record<string, string> = {
            A: 'bg-green-100 text-green-800',
            B: 'bg-yellow-100 text-yellow-800',
            C: 'bg-red-100 text-red-800',
          };
          return (
            <span className={`px-2 py-1 rounded text-xs font-semibold ${colorMap[value] || 'bg-gray-100 text-gray-800'}`}>
              {value}
            </span>
          );
        },
      },
      {
        accessorKey: 'status',
        header: 'Status',
        cell: (info) => {
          const value = info.getValue() as string;
          const colorMap: Record<string, string> = {
            Active: 'bg-green-100 text-green-800',
            Review: 'bg-yellow-100 text-yellow-800',
            Inactive: 'bg-gray-100 text-gray-800',
          };
          return (
            <span className={`px-2 py-1 rounded text-xs font-medium ${colorMap[value] || 'bg-gray-100 text-gray-800'}`}>
              {value}
            </span>
          );
        },
      },
      {
        accessorKey: 'totalOrders',
        header: 'Total Orders',
        cell: (info) => <div className="text-right">{(info.getValue() as number).toLocaleString()}</div>,
      },
      {
        accessorKey: 'region',
        header: 'Region',
      },
      {
        accessorKey: 'lastOrderDate',
        header: 'Last Order',
        cell: (info) => {
          const date = new Date(info.getValue() as string);
          return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        },
      },
    ],
    []
  );

  const table = useReactTable({
    data: mockData,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,
    onGlobalFilterChange: setGlobalFilter,
    globalFilterFn: 'includesString',
    state: {
      sorting,
      columnFilters,
      columnVisibility,
      globalFilter,
    },
  });

  return (
    <div className="h-full flex flex-col">
      {/* Toolbar */}
      <div className="flex items-center justify-between mb-4 pb-3 border-b border-gray-200">
        <div className="flex items-center gap-3 flex-1">
          {/* Global Search */}
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="Search suppliers..."
              value={globalFilter ?? ''}
              onChange={(e) => setGlobalFilter(e.target.value)}
              className="w-full pl-9 pr-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-qualcomm-blue focus:border-transparent"
            />
            {globalFilter && (
              <button
                onClick={() => setGlobalFilter('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>

          {/* Column Visibility Toggle */}
          <div className="relative">
            <button
              onClick={() => setShowColumnMenu(!showColumnMenu)}
              className="flex items-center gap-2 px-3 py-2 text-sm border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
            >
              <Eye className="w-4 h-4" />
              <span>Columns</span>
            </button>
            {showColumnMenu && (
              <>
                <div
                  className="fixed inset-0 z-10"
                  onClick={() => setShowColumnMenu(false)}
                />
                <div className="absolute right-0 top-full mt-1 bg-white border border-gray-200 rounded-md shadow-lg z-20 min-w-[200px] max-h-64 overflow-y-auto">
                  <div className="p-2">
                    {table.getAllColumns()
                      .filter((column) => column.getCanHide())
                      .map((column) => (
                        <label
                          key={column.id}
                          className="flex items-center gap-2 px-3 py-2 hover:bg-gray-50 cursor-pointer rounded"
                        >
                          <input
                            type="checkbox"
                            checked={column.getIsVisible()}
                            onChange={column.getToggleVisibilityHandler()}
                            className="rounded border-gray-300 text-qualcomm-blue focus:ring-qualcomm-blue"
                          />
                          <span className="text-sm">{column.id === 'supplierName' ? 'Supplier Name' : 
                            column.id === 'onTimeDelivery' ? 'On-Time Delivery %' :
                            column.id === 'qualityScore' ? 'Quality Score' :
                            column.id === 'costRating' ? 'Cost Rating' :
                            column.id === 'status' ? 'Status' :
                            column.id === 'totalOrders' ? 'Total Orders' :
                            column.id === 'region' ? 'Region' :
                            column.id === 'lastOrderDate' ? 'Last Order' : column.id}</span>
                        </label>
                      ))}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        {/* Results count */}
        <div className="text-sm text-gray-600">
          {table.getFilteredRowModel().rows.length} of {mockData.length} suppliers
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto border border-gray-200 rounded-lg">
        <table className="w-full">
          <thead className="bg-gray-50 sticky top-0">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    className="px-4 py-3 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider"
                    style={{ width: header.getSize() !== 150 ? header.getSize() : undefined }}
                  >
                    {header.isPlaceholder ? null : (
                      <div
                        className={`flex items-center gap-2 ${
                          header.column.getCanSort() ? 'cursor-pointer select-none hover:text-qualcomm-blue' : ''
                        }`}
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {header.column.getCanSort() && (
                          <span className="text-gray-400">
                            {{
                              asc: <ChevronUp className="w-4 h-4" />,
                              desc: <ChevronDown className="w-4 h-4" />,
                            }[header.column.getIsSorted() as string] ?? (
                              <ChevronsUpDown className="w-4 h-4" />
                            )}
                          </span>
                        )}
                      </div>
                    )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {table.getRowModel().rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-8 text-center text-gray-500">
                  No suppliers found
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => (
                <tr key={row.id} className="hover:bg-gray-50 transition-colors">
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-4 py-3 text-sm text-gray-900">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between mt-4 pt-3 border-t border-gray-200">
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-600">Rows per page:</span>
          <select
            value={table.getState().pagination.pageSize}
            onChange={(e) => table.setPageSize(Number(e.target.value))}
            className="px-2 py-1 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-qualcomm-blue"
          >
            {[10, 20, 30, 50, 100].map((pageSize) => (
              <option key={pageSize} value={pageSize}>
                {pageSize}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-600">
            Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => table.setPageIndex(0)}
              disabled={!table.getCanPreviousPage()}
              className="px-3 py-1 text-sm border border-gray-300 rounded-md disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 transition-colors"
            >
              First
            </button>
            <button
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
              className="px-3 py-1 text-sm border border-gray-300 rounded-md disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 transition-colors"
            >
              Previous
            </button>
            <button
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
              className="px-3 py-1 text-sm border border-gray-300 rounded-md disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 transition-colors"
            >
              Next
            </button>
            <button
              onClick={() => table.setPageIndex(table.getPageCount() - 1)}
              disabled={!table.getCanNextPage()}
              className="px-3 py-1 text-sm border border-gray-300 rounded-md disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 transition-colors"
            >
              Last
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

