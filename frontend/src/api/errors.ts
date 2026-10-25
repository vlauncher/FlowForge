export interface FieldError {
  field: string;
  message: string;
}

export interface ProblemDetailsPayload {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  instance?: string;
  code?: string;
  request_id?: string;
  errors?: FieldError[];
  [key: string]: unknown;
}

export class ApiError extends Error {
  status: number;
  code: string;
  detail?: string;
  requestId?: string;
  errors?: FieldError[];

  constructor(
    status: number,
    code: string,
    detail?: string,
    requestId?: string,
    errors?: FieldError[]
  ) {
    super(detail || code);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.requestId = requestId;
    this.errors = errors;
  }
}
