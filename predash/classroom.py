"""Session credentials with optional persistent Streamlit Secrets profiles."""
import streamlit as st
from predash.kis import KIS, BrokerError


def account_settings(mode=None):
    """Session overrides a complete saved profile; never mix real and demo keys."""
    settings = st.session_state.get('classroom_credentials', {})
    fields = ('key', 'secret', 'cano', 'product')
    if settings and (mode is None or mode == settings.get('mode')):
        return dict(mode=settings['mode'], **{k: settings.get(k, '') for k in fields})
    try:
        saved_mode = str(st.secrets.get('KIS_ENV', 'demo')).strip()
        selected = mode or settings.get('mode') or saved_mode
        empty = dict(mode=selected, **{k: '' for k in fields})
        if st.session_state.get('classroom_saved_disabled') or selected not in ('real', 'demo'):
            return empty
        names = ('APP_KEY', 'APP_SECRET', 'CANO', 'ACNT_PRDT_CD')
        prefix = 'KIS_'
        if selected == 'demo' and any(str(st.secrets.get('KIS_DEMO_'+n, '')).strip() for n in names):
            prefix = 'KIS_DEMO_'
        elif selected != saved_mode:
            return empty
        return dict(mode=selected, **{field: str(st.secrets.get(prefix+name, '')).strip()
                                    for field, name in zip(fields, names)})
    except FileNotFoundError:
        return dict(mode=mode or settings.get('mode', 'demo'), **{k: '' for k in fields})


def connection_form():
    if st.session_state.pop('classroom_clear_inputs', False):
        for key in ('class_key','class_secret','class_cano','class_product'):
            st.session_state.pop(key, None)
    st.subheader('내 증권사 계좌 연결')
    st.caption('현재 세션에 입력하거나, 본인 앱의 Settings → Secrets에 한 번 저장해 다음 접속에도 사용하세요.')
    settings = account_settings()
    if all(settings[k] for k in ('key', 'secret', 'cano', 'product')):
        source = '현재 세션' if st.session_state.get('classroom_credentials') else 'Streamlit Secrets'
        st.success('계좌 설정 준비됨 · ' + ('모의투자' if settings['mode']=='demo' else '실전 조회') + ' · ' + source)
        if st.button('계좌 연결 해제'):
            authorized = st.session_state.get('authorized')
            st.session_state.clear()
            st.session_state.classroom_saved_disabled = True
            if authorized: st.session_state.authorized = True
            st.rerun()
        return
    if st.session_state.get('classroom_saved_disabled'):
        if st.button('Secrets에 저장한 계좌 다시 사용'):
            st.session_state.pop('classroom_saved_disabled', None)
            st.rerun()
    with st.form('classroom_connection'):
        mode = st.radio('투자 환경', ['모의투자','실전 조회'], horizontal=True)
        key = st.text_input('App Key', type='password', key='class_key')
        secret = st.text_input('App Secret', type='password', key='class_secret')
        cano = st.text_input('계좌번호 앞 8자리', type='password', max_chars=8, key='class_cano')
        product = st.text_input('계좌번호 뒤 2자리', max_chars=2, key='class_product')
        submitted = st.form_submit_button('연결 확인', type='primary', use_container_width=True)
    if submitted:
        settings = dict(mode='demo' if mode=='모의투자' else 'real',key=key.strip(),secret=secret.strip(),cano=cano.strip(),product=product.strip())
        try:
            client = KIS(settings=settings)
            with st.spinner('잔고 조회 권한을 확인합니다…'):
                client.balance()
            st.session_state.classroom_credentials = settings
            st.session_state['_kis_client_demo' if settings['mode']=='demo' else '_kis_client'] = client
            st.session_state.classroom_clear_inputs = True
            st.rerun()
        except BrokerError as error:
            st.error(str(error))
    st.info('연결 해제와 로그아웃은 세션 입력과 조회 기록을 지웁니다. Secrets에 저장한 설정은 유지되며 Settings → Secrets에서 삭제할 수 있습니다.')
