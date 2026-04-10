# Hello World Skill

## 목적
입력 텍스트에 인사말을 붙여 반환한다.

## 입력
- text (string, 필수): 인사말을 붙일 대상 텍스트

## 출력
- greeting (string): "Hello, {text}!" 형태의 인사말
- timestamp (string): ISO 8601 실행 시각

## 실행 방법
1. 입력에서 text를 추출한다
2. "Hello, {text}!" 형태로 인사말을 생성한다
3. 현재 시각을 ISO 8601로 가져온다
4. JSON으로 반환한다

## 제약
- text가 빈 문자열이면 "Hello, World!" 반환
- text가 500자를 초과하면 앞 500자만 사용
