export type RiskLevel = 'stable' | 'warning' | 'critical';
export type PatientStatus = 'active' | 'lost_to_follow_up';

export interface TreatmentPlan {
    patient_id: string;
    full_name: string;
    doctor_name: string;
    prescribed_medication: string | null;
    frequency_per_day: number;
    target_systolic: number;
    target_diastolic: number;
    morning_time: string | null; // "HH:MM:SS"
    evening_time: string | null;
}

export interface LatestMeasurement {
    systolic: number | null;
    diastolic: number | null;
    pulse: number | null;
    risk_status: RiskLevel;
    timestamp: string;
}

export interface AppointmentSlot {
    id: string;
    doctor_name: string;
    datetime: string;
}

export interface SchedulePayload {
    patient_id: string;
    morning_time: string; // "HH:MM:SS"
    evening_time: string;
}

export interface ChatMessage {
    id: string;
    sender: 'patient' | 'agent';
    text: string;
    timestamp: string;
    quick_replies?: string[];
}

export interface WsMeasurementEvent {
    event: 'new_measurement_status';
    data: {
        systolic: number | null;
        diastolic: number | null;
        pulse: number | null;
        risk_status: RiskLevel;
    };
}

export interface WsAgentMessageEvent {
    event: 'agent_message';
    data: {
        text: string;
        quick_replies?: string[];
    };
}

export interface WsShowSlotsEvent {
    event: 'show_appointment_slots';
    data: {
        reason: string;
    };
}

export interface WsPatientStatusEvent {
    event: 'patient_status_update';
    data: {
        status: PatientStatus;
    };
}

export interface WsErrorEvent {
    event: 'error';
    data: {
        message: string;
    };
}

export type WsIncomingServerMessage =
    | WsMeasurementEvent
    | WsAgentMessageEvent
    | WsShowSlotsEvent
    | WsPatientStatusEvent
    | WsErrorEvent;
