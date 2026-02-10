/**
 * Service for executing SQL queries against the backend API.
 */

export interface SqlQueryRequest {
    query_id: string;
    parameters?: Record<string, any>;
}

export interface SqlQueryResponse {
    query_id: string;
    status: string;
    columns: string[];
    rows: Record<string, any>[];
    row_count: number;
    execution_time_ms?: number;
    statement_id?: string;
}

/**
 * Executes a pre-configured SQL query.
 * 
 * @param params The query ID and optional parameters
 * @returns The query results
 */
export const executeSqlQuery = async (params: SqlQueryRequest): Promise<SqlQueryResponse> => {
    // Safety check to avoid 422 errors for unconfigured widgets
    if (!params.query_id) {
        console.warn('⚠️ executeSqlQuery called without query_id, skipping request');
        return {
            query_id: '',
            status: 'error',
            columns: [],
            rows: [],
            row_count: 0
        };
    }

    const response = await fetch('/api/sql/execute', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(params),
    });

    if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(errorData.detail || `HTTP ${response.status}`);
    }

    return await response.json();
};
