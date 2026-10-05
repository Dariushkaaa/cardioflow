import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useGetLatestMeasurementQuery, useGetTreatmentPlanQuery } from '@shared/api/baseApi';
import type { RiskLevel } from '@shared/api/types';
import { useAppSelector } from '@shared/lib/hooks';
import styles from './HomePage.module.css';

const RISK_LABEL: Record<RiskLevel, string> = {
    stable: 'В норме',
    warning: 'Выше целевого',
    critical: 'Повышенный риск',
};

const RISK_CLASS: Record<RiskLevel, string> = {
    stable: '',
    warning: styles.statusWarning,
    critical: styles.statusCritical,
};

/** Ближайший прием лекарства по расписанию ("HH:MM:SS"), локальное время браузера. */
function nextDose(morning?: string | null, evening?: string | null): string | null {
    const times = [morning, evening].filter((t): t is string => Boolean(t)).map((t) => t.slice(0, 5));
    if (times.length === 0) return null;
    const now = new Date();
    const current = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
    const sorted = [...times].sort();
    const upcoming = sorted.find((t) => t > current);
    return upcoming ? `сегодня в ${upcoming}` : `завтра в ${sorted[0]}`;
}

export const HomePage: React.FC = () => {
    const navigate = useNavigate();
    const { data: treatment } = useGetTreatmentPlanQuery();
    const { data: latest } = useGetLatestMeasurementQuery();
    const live = useAppSelector((state) => state.realtime.measurement);
    const patientStatus = useAppSelector((state) => state.realtime.patientStatus);

    // Свежие данные из WebSocket важнее сохраненного последнего замера
    const measurement = live ?? (latest
        ? { systolic: latest.systolic, diastolic: latest.diastolic, pulse: latest.pulse, risk: latest.risk_status }
        : null);

    const firstName = treatment?.full_name ? treatment.full_name.split(' ')[1] : null;
    const dose = nextDose(treatment?.morning_time, treatment?.evening_time);

    return (
        <div className={styles.homePage}>
            <header className={styles.header}>
                <div>
                    <h1 className={styles.greetingTitle}>Здравствуйте{firstName ? `, ${firstName}` : ''}!</h1>
                    {treatment && (
                        <span className={styles.diagnosisTag}>
                            Целевое давление {treatment.target_systolic}/{treatment.target_diastolic}
                            {treatment.prescribed_medication ? ` • ${treatment.prescribed_medication}` : ''}
                        </span>
                    )}
                </div>
            </header>

            {patientStatus === 'lost_to_follow_up' && (
                <div className={styles.reminderCard}>
                    <div style={{ fontSize: '13px', color: '#4C0519' }}>
                        Давно не было данных от вас. Напишите в чат, как вы себя чувствуете.
                    </div>
                </div>
            )}

            <div className={styles.dashboardGrid}>
                {/* Карточка текущего статуса АД */}
                <div className={styles.metricCard}>
                    <div className={styles.metricHeader}>
                        <span>Ваши показатели</span>
                        {measurement && (
                            <span className={`${styles.statusBadge} ${RISK_CLASS[measurement.risk]}`}>
                                ● {RISK_LABEL[measurement.risk]}
                            </span>
                        )}
                    </div>

                    {measurement ? (
                        <>
                            <div className={styles.metricValues}>
                                <span className={styles.mainValue}>
                                    {measurement.systolic ?? '—'}/{measurement.diastolic ?? '—'}
                                </span>
                                <span className={styles.unit}>мм рт. ст.</span>
                            </div>
                            <div style={{ fontSize: '14px', color: '#64748B' }}>
                                Пульс <strong>{measurement.pulse ?? '—'}</strong> уд/мин
                            </div>
                        </>
                    ) : (
                        <div style={{ fontSize: '14px', color: '#64748B' }}>
                            Замеров пока нет. Отправьте давление в чат, например: «Давление 130/85, пульс 72».
                        </div>
                    )}
                </div>

                {/* Напоминание о приеме лекарств */}
                {dose && (
                    <div className={styles.reminderCard}>
                        <div>
                            <div style={{ fontWeight: 600, color: '#BE123C' }}>Напоминание</div>
                            <div style={{ fontSize: '13px', color: '#4C0519', marginTop: '2px' }}>
                                Следующий прием препарата {dose}
                            </div>
                        </div>
                        <span style={{ fontSize: '20px' }}>›</span>
                    </div>
                )}
            </div>

            <div style={{ fontWeight: 600, marginTop: '8px' }}>Быстрые действия</div>
            <div className={styles.quickActionsGrid}>
                <button className={styles.actionButton} onClick={() => navigate('/chat')}>
                    <span>💬</span>
                    <span>Написать в чат</span>
                </button>
                <button className={styles.actionButton} onClick={() => navigate('/treatment')}>
                    <span>💊</span>
                    <span>План лечения</span>
                </button>
            </div>
        </div>
    );
};
