# One Minute Pitch

## 10-second version

이미 쓰는 AI에 검증된 AI 작업반을 설치하세요.

## 30-second version

Cambrian은 사용자가 직접 에이전트를 설계하지 않아도, Auth Bug Core 같은 AI 작업반을 로컬 프로젝트에 설치하고, 이미 쓰는 AI에 일을 맡기고, 결과를 검증하게 해주는 로컬 실행 엔진입니다.

## 60-second version

대부분의 사용자는 AI를 잘 쓰지만, 매번 어떤 맥락을 줘야 하는지, 어떤 역할을 맡겨야 하는지, 결과를 어떻게 검증해야 하는지 직접 조립해야 합니다.

Cambrian은 이 문제를 worker pack으로 풉니다. 예를 들어 Auth Bug Core는 Python + pytest + 좁은 auth/login 버그 수정에 맞춘 작업반입니다. 사용자는 이 pack을 로컬 프로젝트에 설치하고, 이미 쓰는 AI에 생성된 packet을 붙여넣고, 돌아온 답변을 Cambrian에 다시 넣어 validation handoff까지 확인합니다.

웹은 작업반을 고르는 hiring desk입니다. 실제 설치, 작업 전달, 검증, proof는 로컬 Cambrian runtime이 수행합니다.

첫 공개 데모는 실제 AI 호출 없이 canned AI reply fixture를 사용합니다. 그래서 네트워크나 provider key 없이도 Auth Bug Core가 설치되고, job이 시작되고, 답변이 ingest되고, validation까지 이어지는 핵심 흐름을 재현할 수 있습니다.

## Do Not Say

- 완전 자율
- 모든 분야 자동화
- 무조건 성공한다는 표현
- 근거 없는 최고 성능 표현
- enterprise orchestration
