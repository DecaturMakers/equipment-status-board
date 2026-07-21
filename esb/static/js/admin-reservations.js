(() => {
    const dataElement = document.getElementById('admin-reservation-calendar-data');
    if (!dataElement) {
        return;
    }

    const data = JSON.parse(dataElement.textContent);
    const panes = document.querySelectorAll('[data-admin-reservation-pane]');
    const tabs = document.querySelectorAll('[data-admin-reservation-tab]');
    const modalElement = document.getElementById('reservationDetailModal');
    const modal = modalElement && window.bootstrap ? new window.bootstrap.Modal(modalElement) : null;

    const showPane = (name) => {
        panes.forEach((pane) => {
            pane.classList.toggle('d-none', pane.dataset.adminReservationPane !== name);
        });
        tabs.forEach((tab) => {
            const active = tab.dataset.adminReservationTab === name;
            tab.classList.toggle('active', active);
            tab.setAttribute('aria-selected', String(active));
        });
    };

    const setDetailField = (name, value) => {
        const field = modalElement?.querySelector(`[data-reservation-field="${name}"]`);
        if (field) {
            field.textContent = value || '—';
        }
    };

    const setOptionalDetailRow = (name, value) => {
        const row = modalElement?.querySelector(`[data-reservation-detail-row="${name}"]`);
        row?.classList.toggle('d-none', !value);
        setDetailField(name, value);
    };

    const reservationActionUrl = (template, reservationId) => (
        template.replace('/0/', `/${reservationId}/`)
    );

    const showDetails = (reservationId) => {
        const reservation = data.details[String(reservationId)];
        if (!reservation || !modal) {
            return;
        }
        setDetailField('equipment', reservation.equipment);
        setDetailField('area', reservation.area);
        setDetailField('user', reservation.user);
        setDetailField('time', `${reservation.starts_at_label} to ${reservation.ends_at_label} ET`);
        const status = modalElement.querySelector('[data-reservation-field="status"]');
        status.textContent = reservation.status;
        status.className = `badge text-bg-${reservation.status === 'active' ? 'success' : 'secondary'}`;
        setDetailField('created_by', reservation.created_by);
        setOptionalDetailRow('canceled_by', reservation.canceled_by);
        setOptionalDetailRow('replaces', reservation.replaces_label);
        setOptionalDetailRow('replaced_by', reservation.replaced_by_label);
        setOptionalDetailRow('overrides', reservation.override_codes.join(', '));
        setDetailField('note', reservation.note);
        const actions = modalElement.querySelector('[data-reservation-actions]');
        actions.classList.toggle('d-none', reservation.status !== 'active');
        const edit = modalElement.querySelector('[data-reservation-edit]');
        const cancel = modalElement.querySelector('[data-reservation-cancel]');
        edit.href = reservationActionUrl(modalElement.dataset.editUrlTemplate, reservation.id);
        cancel.action = reservationActionUrl(modalElement.dataset.cancelUrlTemplate, reservation.id);
        modal.show();
    };

    tabs.forEach((tab) => {
        tab.addEventListener('click', () => showPane(tab.dataset.adminReservationTab));
    });
    document.querySelectorAll('[data-reservation-detail]').forEach((button) => {
        button.addEventListener('click', () => showDetails(button.dataset.reservationDetail));
    });

    if (!window.DayPilot || !data.columns.length) {
        const fallback = document.getElementById('admin-reservation-calendar-fallback');
        const calendarElement = document.getElementById('admin-reservation-calendar');
        if (calendarElement) {
            calendarElement.innerHTML = '<p class="calendar-message">Calendar view unavailable.</p>';
        }
        fallback?.classList.remove('d-none');
        showPane('list');
        return;
    }

    const calendarElement = document.getElementById('admin-reservation-calendar');
    calendarElement.textContent = '';
    const calendar = new DayPilot.Calendar('admin-reservation-calendar', {
        viewType: 'Resources',
        startDate: data.startDate,
        columns: data.columns,
        events: data.events,
        eventMoveHandling: 'Disabled',
        eventResizeHandling: 'Disabled',
        timeRangeSelectedHandling: 'Disabled',
        eventClickHandling: 'Enabled',
        eventDeleteHandling: 'Disabled',
        durationBarVisible: false,
        cellHeight: 28,
        businessBeginsHour: 7,
        businessEndsHour: 23,
        showNonBusiness: false,
        headerHeight: 34,
        onEventClick: (args) => {
            const eventId = typeof args.e.id === 'function' ? args.e.id() : args.e.data.id;
            showDetails(eventId);
        },
    });
    calendar.init();
    showPane('calendar');
})();
