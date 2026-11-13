import { ButtonLink } from '@/components/Button';
import { EmptyState } from '@/components/States';

export function NotFoundPage() {
  return (
    <EmptyState
      title="Такой страницы нет"
      text="Возможно, ссылка устарела."
      action={<ButtonLink to="/">К моим доскам</ButtonLink>}
    />
  );
}
