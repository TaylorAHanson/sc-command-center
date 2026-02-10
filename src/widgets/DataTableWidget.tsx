import React, { useMemo, useState, useEffect } from 'react';
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
import { Search, ChevronDown, ChevronUp, ChevronsUpDown, X, Eye, RefreshCw, AlertCircle } from 'lucide-react';
import type { WidgetProps } from '../widgetRegistry';
import { executeSqlQuery } from '../services/sqlQueryService';

// Widget configuration interface
interface DataTableWidgetConfig {
  queryId: string;
  title?: string;
  parameters?: Record<string, any>;
  refreshInterval?: number; // in seconds
}

export const DataTableWidget: React.FC<WidgetProps> = ({ data }) => {
  // Extract configuration from widget data with defaults
  const config = (data as DataTableWidgetConfig) || {};
  const queryId = config.queryId || 'supplier_performance';
  const title = config.title;
  const parameters = config.parameters;
  const refreshInterval = config.refreshInterval;

  // State for data fetching
  const [tableData, setTableData] = useState<Record<string, any>[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  // Table state
  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});
  const [globalFilter, setGlobalFilter] = useState('');
  const [showColumnMenu, setShowColumnMenu] = useState(false);

  // Fetch data from SQL API
  const fetchData = React.useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await executeSqlQuery({
        query_id: queryId,
        parameters: parameters,
      });
      setTableData(response.rows);
      setLastRefresh(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch data');
      console.error('Error fetching table data:', err);
    } finally {
      setIsLoading(false);
    }
  }, [queryId, parameters]);

  // Initial data fetch
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Auto-refresh if configured
  useEffect(() => {
    if (refreshInterval && refreshInterval > 0) {
      const interval = setInterval(fetchData, refreshInterval * 1000);
      return () => clearInterval(interval);
    }
  }, [refreshInterval, fetchData]);

  // Generate columns dynamically from data
  const columns = useMemo<ColumnDef<Record<string, any>>[]>(() => {
    if (tableData.length === 0) return [];

    const firstRow = tableData[0];
    return Object.keys(firstRow).map((key) => ({
      id: key,
      accessorKey: key,
      header: () => {
        // Convert snake_case to Title Case
        if (typeof key !== 'string') return String(key);
        return key
          .split('_')
          .map(word => word.charAt(0).toUpperCase() + word.slice(1))
          .join(' ');
      },
      cell: (info) => {
        const value = info.getValue();

        // Handle null/undefined
        if (value === null || value === undefined) {
          return <span className="text-gray-400">—</span>;
        }

        // Format based on type
        if (typeof value === 'number') {
          // Check if it's a percentage (0-100 range with decimals)
          if (key.toLowerCase().includes('percent') || key.toLowerCase().includes('rate')) {
            return <span>{value.toFixed(1)}%</span>;
          }
          // Format large numbers with commas
          if (value > 999) {
            return <span>{value.toLocaleString()}</span>;
          }
          // Format decimals
          if (value % 1 !== 0) {
            return <span>{value.toFixed(2)}</span>;
          }
          return <span>{value}</span>;
        }

        // Format dates
        if (key.toLowerCase().includes('date') || key.toLowerCase().includes('time')) {
          try {
            const date = new Date(String(value));
            if (!isNaN(date.getTime())) {
              return <span>{date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</span>;
            }
          } catch {
            // Not a valid date, fall through
          }
        }

        // Status badges
        if (key.toLowerCase().includes('status')) {
          const statusColors: Record<string, string> = {
            active: 'bg-green-100 text-green-800',
            inactive: 'bg-gray-100 text-gray-800',
            pending: 'bg-yellow-100 text-yellow-800',
            review: 'bg-yellow-100 text-yellow-800',
            completed: 'bg-blue-100 text-blue-800',
            failed: 'bg-red-100 text-red-800',
            error: 'bg-red-100 text-red-800',
          };
          const colorClass = statusColors[String(value).toLowerCase()] || 'bg-gray-100 text-gray-800';
          return (
            <span className={`px-2 py-1 rounded text-xs font-medium ${colorClass}`}>
              {String(value)}
            </span>
          );
        }

        // Default: render as string
        return <span>{String(value)}</span>;
      },
    }));
  }, [tableData]);

  const table = useReactTable({
    data: tableData,
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

  // Loading state
  if (isLoading && tableData.length === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 text-qualcomm-blue animate-spin mx-auto mb-2" />
          <p className="text-gray-600">Loading data...</p>
        </div>
      </div>
    );
  }

  // Error state
  if (error && tableData.length === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <AlertCircle className="w-8 h-8 text-red-500 mx-auto mb-2" />
          <p className="text-gray-900 font-medium mb-1">Failed to load data</p>
          <p className="text-gray-600 text-sm mb-4">{error}</p>
          <button
            onClick={fetchData}
            className="px-4 py-2 bg-qualcomm-blue text-white rounded-md hover:bg-qualcomm-navy transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Title bar */}
      {title && (
        <div className="mb-3">
          <h3 className="text-lg font-semibold text-qualcomm-navy">{title}</h3>
        </div>
      )}
      {/* Toolbar */}
      <div className="flex items-center justify-between mb-4 pb-3 border-b border-gray-200">
        {/* Refresh button */}
        <button
          onClick={fetchData}
          disabled={isLoading}
          className="p-2 text-gray-600 hover:text-qualcomm-blue hover:bg-gray-50 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          title="Refresh data"
        >
          <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
        </button>
        <div className="flex items-center gap-3 flex-1 ml-2">
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
                          <span className="text-sm">
                            {column.id
                              ? column.id.split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ')
                              : 'Unknown'}
                          </span>
                        </label>
                      ))}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        {/* Results count and last refresh */}
        <div className="text-sm text-gray-600 flex items-center gap-4">
          <span>{table.getFilteredRowModel().rows.length} of {tableData.length} rows</span>
          {lastRefresh && (
            <span className="text-xs text-gray-500">
              Updated {lastRefresh.toLocaleTimeString()}
            </span>
          )}
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
                        className={`flex items-center gap-2 ${header.column.getCanSort() ? 'cursor-pointer select-none hover:text-qualcomm-blue' : ''
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
                  No data found
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
